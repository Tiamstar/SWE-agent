# 多项目索引方案对比

## 场景假设
- **项目数量**: 10 个不同的 HarmonyOS 仓库
- **项目规模**: 每个项目 ~1000 个 C/C++ 文件
- **首次索引时间**: ~10 分钟/项目
- **使用模式**: 每周切换 3-5 个项目，每个项目运行 2-3 次任务

## 方案 A：Neo4j 在 Devcontainer（当前设计）

### ❌ 当前问题
```python
# 当前实现没有项目隔离！
# 所有项目数据混在一起
MERGE (f:File {name: 'src/main.cpp'})  # ← 哪个项目的 main.cpp？
```

**问题：**
1. 多个项目的文件名可能重复 → 数据污染
2. 无法区分不同项目的代码
3. 无法自动检测项目是否已索引

### ✅ 优化后的方案 A（推荐）

**核心改进：为所有节点添加 `project_id` 属性**

```python
# 索引时
project_id = hashlib.sha256(repo_path.encode()).hexdigest()[:16]
MERGE (f:File {name: 'src/main.cpp', project_id: 'abc123...'})

# 查询时（自动过滤）
MATCH (f:File {project_id: $project_id})
WHERE f.name CONTAINS $name
```

**效率分析：**

| 操作 | 首次运行 | 第二次运行 | 切换项目 |
|------|---------|-----------|---------|
| 索引时间 | 10 分钟（首次） | 0 秒（已索引） | 10 分钟（首次）/ 0 秒（已索引） |
| 内存占用 | 所有项目共享 ~500MB | 不增加 | 不增加 |
| 磁盘占用 | ~100MB/项目 × 10 = 1GB | 不增加 | 不增加 |

**优势：**
✅ 索引一次，永久使用（跨容器、跨任务）
✅ 多项目共存，自动隔离
✅ 快速切换项目（0 秒，如果已索引）
✅ 开发调试友好（可以直接访问 Neo4j Browser）

**实现要点：**
```python
# 1. 自动检测是否已索引
def is_project_indexed(project_id: str) -> bool:
    result = session.run(
        "MATCH (f:File {project_id: $pid}) RETURN count(f) as cnt",
        pid=project_id
    )
    return result.single()['cnt'] > 0

# 2. 自动触发索引（在 Harmony Coordinator 启动时）
if not is_project_indexed(current_project_id):
    logger.info(f"项目未索引，开始建立索引...")
    indexer.run_full_scan(project_id=current_project_id)
else:
    logger.info(f"项目已索引，直接使用现有数据")

# 3. 查询时自动过滤
def get_file_dependencies(self, file_name: str, project_id: str):
    return self._run("""
        MATCH (f1:File {project_id: $pid})-[:INCLUDES]->(f2:File {project_id: $pid})
        WHERE f1.name CONTAINS $name
        RETURN f1.name as source, f2.name as dependency
    """, {"name": file_name, "pid": project_id})
```

---

## 方案 B：Neo4j 在运行时容器

### 实现方式
每次运行任务时：
1. 启动一个新的 SWE-ReX 容器
2. 在容器内启动 Neo4j
3. 索引当前项目（10 分钟）
4. 运行任务
5. 容器销毁，数据丢失

**效率分析：**

| 操作 | 首次运行 | 第二次运行 | 切换项目 |
|------|---------|-----------|---------|
| 索引时间 | 10 分钟 | 10 分钟（每次！） | 10 分钟（每次！） |
| 内存占用 | ~500MB/容器 | ~500MB/容器 | ~500MB/容器 |
| 磁盘占用 | ~100MB（临时） | ~100MB（临时） | ~100MB（临时） |

**劣势：**
❌ 每次运行都要重新索引（10 分钟 × 每次任务）
❌ 每周 3-5 个项目 × 2-3 次任务 = 60-150 分钟浪费在重复索引上
❌ 无法利用缓存
❌ 多个容器同时运行时，内存占用成倍增加

**唯一优势：**
✅ 网络配置简单（localhost 直连）
✅ 数据天然隔离（容器销毁即清理）

---

## 📈 实际使用场景对比

### 场景 1：同一项目运行 3 次任务

| 方案 | 总耗时 | 说明 |
|------|--------|------|
| **优化后的 A** | 10 分钟（首次索引）+ 0 + 0 = **10 分钟** | ✅ 第 2、3 次直接使用缓存 |
| **方案 B** | 10 + 10 + 10 = **30 分钟** | ❌ 每次都要重新索引 |

**效率提升：3倍**

### 场景 2：一周内切换 5 个项目，每个项目 2 次任务

| 方案 | 总耗时 | 说明 |
|------|--------|------|
| **优化后的 A** | 5 × 10（首次）+ 5 × 0（第二次）= **50 分钟** | ✅ 每个项目只索引一次 |
| **方案 B** | 10 × 10 = **100 分钟** | ❌ 10 次任务，10 次索引 |

**效率提升：2倍**

### 场景 3：长期使用（10 个项目，每月重复使用）

| 方案 | 首月耗时 | 次月耗时 | 说明 |
|------|---------|---------|------|
| **优化后的 A** | 100 分钟索引 + 任务时间 | **仅任务时间** | ✅ 数据持久化，次月零索引 |
| **方案 B** | 100 分钟索引 + 任务时间 | **100 分钟索引 + 任务时间** | ❌ 每月重复索引 |

**长期效率提升：无限倍**

---

## 🎯 结论与推荐

### 推荐：**优化后的方案 A**

**原因：**
1. **效率碾压**：避免重复索引，节省 50%-300% 时间
2. **资源节省**：共享 Neo4j 实例，内存占用更低
3. **开发友好**：可以直接访问 Neo4j Browser 调试查询
4. **适合多 Agent 系统**：所有 Agent 共享同一份代码图

**需要的改进：**
1. ✅ 添加 `project_id` 到所有节点和关系
2. ✅ 实现自动检测和增量索引
3. ✅ 修改所有查询添加 `project_id` 过滤

---

## 🚀 自动索引机制设计

```python
class HarmonyCoordinator:
    def __init__(self, env, repo_path, ...):
        self.repo_path = repo_path
        self.project_id = self._get_project_id(repo_path)

        # 启动时自动检测并索引
        self._ensure_project_indexed()

    def _get_project_id(self, repo_path: Path) -> str:
        """生成项目唯一标识"""
        import hashlib
        canonical = str(repo_path.resolve())
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _ensure_project_indexed(self):
        """确保当前项目已索引"""
        from tools.harmony_graph.lib.core import CodeGraphAgent

        agent = CodeGraphAgent()
        try:
            if not agent.is_project_indexed(self.project_id):
                self.logger.info(f"🔍 检测到新项目，开始建立代码图索引...")
                self.logger.info(f"   项目路径: {self.repo_path}")
                self.logger.info(f"   项目 ID: {self.project_id}")

                agent.index_project(
                    str(self.repo_path),
                    project_id=self.project_id,
                    force_clean=False  # 增量索引
                )

                self.logger.info(f"✅ 索引完成！后续运行将直接使用缓存")
            else:
                self.logger.info(f"✅ 项目已索引，使用现有代码图数据")
                self.logger.info(f"   项目 ID: {self.project_id}")
        finally:
            agent.close()
```

**用户体验：**
```bash
# 第一次运行新项目
$ python tools/run_harmony_mas.py --repo_path /path/to/new_project --issue "..."
🔍 检测到新项目,开始建立代码图索引...
   项目路径: /path/to/new_project
   项目 ID: a1b2c3d4e5f6g7h8
⏳ 索引中... (预计 10 分钟)
✅ 索引完成！后续运行将直接使用缓存
[继续执行任务...]

# 第二次运行同一项目
$ python tools/run_harmony_mas.py --repo_path /path/to/new_project --issue "..."
✅ 项目已索引，使用现有代码图数据
   项目 ID: a1b2c3d4e5f6g7h8
[直接执行任务，0 秒索引时间]
```

---

## 📝 实现清单

- [ ] 修改 `IndexerEngine` 添加 `project_id` 参数
- [ ] 更新所有 Cypher 查询添加 `project_id` 过滤
- [ ] 实现 `is_project_indexed()` 方法
- [ ] 在 `HarmonyCoordinator` 添加自动索引逻辑
- [ ] 更新 Neo4j 索引添加 `project_id` 字段
- [ ] 测试多项目场景
