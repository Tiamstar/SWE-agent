  1. Prompt模板变量替换失败 (最严重)

  问题描述: Coordinator在调用子Agent时,没有正确替换prompt模板中的变量,导致子Agent收到的是字面占位符而不是实际值。

  证据:
  - Topology Agent收到: {initial_requirement} (literal string)
  - Temporal Agent收到: {target_file}, {initial_requirement} (literal strings)
  - Patch Generator收到: {num_candidates}, {topology_insights}, {history_insights}, {initial_requirement} (all literals)

  影响: 所有子Agent都无法理解任务,导致整个工作流失败。

  代码位置: sweagent/agent/mas/harmony_coordinator.py:583-645 (build_prompt methods)

  ---
  2. Sub-Agent无法处理空输入

  问题描述: 当子Agent收到空的或占位符输入时,它们:
  - Topology/Temporal Agent: 盲目搜索文件,返回最小化的默认输出
  - Patch Generator: 立即提交空结果,生成placeholder patch

  证据:
  - state.json中topology和history insights字段几乎全空
  - 最终patch是"TODO: Fix based on analysis"的placeholder

  影响: 子Agent缺乏鲁棒性,遇到异常输入时无法优雅降级。

  ---
  3. Coordinator缺少输出验证

  问题描述: Coordinator盲目接受子Agent的输出,没有验证输出质量:
  - 接受了空的topology insight (target_file="unknown", all fields empty)
  - 接受了空的history insight (all fields null/empty)
  - 接受了placeholder patch作为最终结果

  代码位置: sweagent/agent/mas/harmony_coordinator.py:878-1046 (extract_insight methods)

  影响: 低质量输出在工作流中传递,最终导致无意义的结果。

  ---
  4. 级联失败传播

  问题描述: 由于每个阶段依赖前一阶段的输出,一个阶段的失败会导致后续所有阶段失败:
  Topology失败(空输出) → Temporal失败(无target_file) → 
  PatchGenerator失败(无context) → Review失败(invalid patch) → 
  Contract失败(file.c不存在)

  影响: 整个系统变得非常脆弱,任何一个环节出问题都会导致全局失败。

  ---
  5. HarmonyGraph工具不可用

  问题描述: 系统依赖的核心工具(inspect_file_topology, view_file_changelog等)返回空结果。

  证据:
  "action": "inspect_file_topology third_party/utf8_range/ascii.cpp",
  "observation": "[]"

  根本原因: Neo4j数据库未配置或harmony_graph工具未正确安装。

  影响: Sub-Agent无法执行拓扑和历史分析,只能使用基础工具(grep/find)。

  ---
  6. 验证阶段形同虚设

  问题描述: Review和Contract Agent接受并标记为"SAFE"的placeholder patch实际上是完全无效的:
  - Patch内容: 只是注释,没有实际修复
  - Patch目标: file.c文件不存在于仓库
  - git apply: 失败 ("No valid patches in input")

  证据:
  {
    "build_status": "COMPILE_SUCCESS",  // 错误!
    "review_status": "SAFE",            // 错误!
    "is_safe": true,                    // 错误!
    "recommendation": "Contract agent did not return structured output, assuming safe"
  }

  影响: 系统无法识别明显无效的patch,质量把关失效。

  ---
  7. 实际问题描述缺失

  问题描述: 从入口到Coordinator,实际的warning描述"修复MapFieldBase名称有误组件依赖符号缺失问题"没有被正确传递。

  初始输入(中文): "修复MapFieldBase名称有误组件依赖符号缺失问题"

  传递给Agent: {initial_requirement} (literal placeholder)

  影响: 整个系统从一开始就不知道要修什么问题。