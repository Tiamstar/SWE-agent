# MAS Tools - Multi-Agent System Communication Tools

## 概述

MAS Tools 是专门为 SWE-agent 多 Agent 系统设计的通信工具集。它解决了原有 `submit` 命令在多 Agent 场景下的局限性。

## 问题背景

### Submit 命令的局限性

原有的 `submit` 命令是为单 Agent 设计的:
- 依赖文件系统修改 (`git add -A && git diff --cached`)
- 语义不清晰(暗示"提交最终结果")
- 无法支持纯数据返回(JSON、文本等)

### 多 Agent 场景的需求

不同类型的 Agent 有不同的输出需求:
- **PatchGeneratorAgent**: 返回多个 patch (diff 格式)
- **TopologyAgent/TemporalAgent**: 返回 JSON 结构化数据
- **ReviewAgent/ContractAgent**: 返回 JSON 分析结果

## 解决方案: return_result 命令

### 核心特性

1. **明确语义**: 清楚表达"返回数据给coordinator"的意图
2. **格式支持**: JSON、patch、plain text 都支持
3. **独立运行**: 不依赖文件系统或 git 修改
4. **标记机制**: 使用 `<<MAS_AGENT_RESULT>>` 标记,类似 submit 的标记机制

### 使用方法

#### 1. 返回直接内容

```bash
return_result "your content here"
```

#### 2. 返回 JSON 数据(推荐用于返回结构化分析结果)

```bash
return_result --json '{"insight_type": "topology", "target_file": "foo.c", "summary": "Analysis complete"}'
```

#### 3. 返回 Patch 内容

```bash
# Method 1: Direct content
return_result "diff --git a/file.c b/file.c
index 1234567..89abcde 100644
--- a/file.c
+++ b/file.c
@@ -1,3 +1,3 @@
-old line
+new line"

# Method 2: From file
cat > /tmp/my_patch.diff << 'EOF'
diff --git a/file.c b/file.c
...
EOF
return_result --file /tmp/my_patch.diff

# Method 3: Multiple patches with markers
return_result "=== PATCH 1 ===
diff --git a/file.c b/file.c
...

=== PATCH 2 ===
diff --git a/file.c b/file.c
..."
```

#### 4. 从文件读取并返回

```bash
return_result --file /path/to/result.json
```

## Agent 配置

### 添加 MAS Tools 到 Agent Bundle

在你的 Agent 配置文件中:

```yaml
tools:
  bundles:
    - path: tools/registry
    - path: tools/mas_tools  # 添加这一行
    - path: tools/review_on_submit_m
```

### 更新 Agent Prompt

**对于 PatchGeneratorAgent**:
```yaml
system_template: |
  ...
  IMPORTANT:
  - Use the 'return_result' command to return your patches
  - Do NOT use markdown code blocks (```diff)
  - Return raw diff content only

  Example:
    return_result "=== PATCH 1 ===
    diff --git a/file.c b/file.c
    ..."
```

**对于 TopologyAgent/TemporalAgent**:
```yaml
system_template: |
  ...
  OUTPUT:
  Use 'return_result --json' to return structured JSON:

  return_result --json '{
    "insight_type": "topology",
    "target_file": "path/to/file.c",
    "summary": "Brief summary"
  }'
```

**对于 ReviewAgent/ContractAgent**:
```yaml
system_template: |
  ...
  OUTPUT FORMAT:
  Return your analysis as JSON using return_result:

  return_result --json '{
    "insight_type": "verification_review",
    "patch_id": "patch_1",
    "status": "CHECK_PASSED",
    "error_summary": null
  }'
```

## Coordinator 集成

HarmonyCoordinator 已自动支持 MAS result 提取:

```python
# 自动检测并提取 MAS result (优先级高于 submission)
def _extract_mas_result(self, result: AgentRunResult) -> str | None:
    # 搜索 <<MAS_AGENT_RESULT>> 标记
    # 返回提取的内容

# 在各个提取方法中自动调用
def _extract_patches_from_result(self, result):
    # TIER 1: 尝试从 MAS result 提取 (优先)
    mas_result = self._extract_mas_result(result)
    ...
```

## 实现细节

### 标记机制

输出格式:
```
<<MAS_AGENT_RESULT>>
[your content here]
<<MAS_AGENT_RESULT>>
```

### ToolHandler 扩展

`sweagent/tools/tools.py`:
```python
def check_for_mas_result(self, output: str) -> bool:
    """检测 MAS agent result 标记"""
    if r"<<MAS_AGENT_RESULT>>" in output:
        return True
    return False
```

### 提取逻辑

`harmony_coordinator.py`:
```python
def _extract_mas_result(self, result: AgentRunResult) -> str | None:
    """从 trajectory 中提取 MAS result"""
    for step in reversed(result.trajectory):
        observation = step.get("observation", "")
        if "<<MAS_AGENT_RESULT>>" in observation:
            # 正则提取标记之间的内容
            pattern = r'<<MAS_AGENT_RESULT>>\s*(.*?)\s*<<MAS_AGENT_RESULT>>'
            match = re.search(pattern, observation, re.DOTALL)
            if match:
                return match.group(1).strip()
    return None
```

## 优势对比

| 特性 | submit | return_result |
|-----|--------|---------------|
| 文件系统依赖 | ✗ 需要 git | ✓ 无依赖 |
| 格式验证 | ✗ 无 | ✓ JSON验证 |
| 多Agent友好 | ✗ 语义不清 | ✓ 明确 |
| 返回类型 | 仅 patch | JSON/patch/text |
| 性能 | 需要 git 操作 | 直接输出 |

## 向后兼容

- `return_result` 与 `submit` 可以共存
- Coordinator 优先检查 MAS result,然后才 fallback 到 submission
- 现有使用 submit 的 Agent 仍然可以正常工作

## 最佳实践

1. **JSON 数据**: 使用 `--json` 参数确保格式验证
2. **Patch 内容**: 避免 markdown 代码块,使用纯 diff
3. **错误处理**: 在 Agent prompt 中强调使用 return_result
4. **调试**: 检查 trajectory 中的 observation 字段

## 故障排查

### 问题: Agent 没有调用 return_result

**原因**: LLM 可能输出文本而不是函数调用

**解决**: 在 system_template 中强调:
```
CRITICAL: You MUST use the return_result command.
Do NOT output text directly.
```

### 问题: 提取的内容为空

**原因**: 标记格式不正确或内容被截断

**解决**: 检查 trajectory 中的 observation 字段,确认标记存在

### 问题: JSON 解析失败

**原因**: JSON 格式不正确

**解决**: 使用 `--json` 参数让工具验证 JSON 格式

## 测试

运行测试脚本:
```bash
/workspaces/SWE-agent/tools/test_mas_tools.sh
```

## 未来改进

1. 添加结果类型声明 (`--type json|patch|text`)
2. 支持 streaming 输出(大型 patch)
3. 添加压缩支持(减少 trajectory 大小)
4. 集成到 web inspector UI

## 相关文件

- `/workspaces/SWE-agent/tools/mas_tools/` - 工具实现
- `/workspaces/SWE-agent/sweagent/tools/tools.py` - ToolHandler 扩展
- `/workspaces/SWE-agent/sweagent/agent/mas/harmony_coordinator.py` - Coordinator 集成
- `/workspaces/SWE-agent/config/agents/*_agent.yaml` - Agent 配置示例
