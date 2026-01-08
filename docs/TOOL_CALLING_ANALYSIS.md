# SWE-Agent 工具调用（Tool Calling）跨 LLM 提供商分析

## 概述

这份文档分析了 SWE-Agent 如何向不同的 LLM 提供商传递工具定义及工具调用格式，以及是否对不同提供商进行了差异化处理。

---

## 核心发现

### ✅ **关键结论：统一的工具格式 + LiteLLM 自动转换**

SWE-Agent 采用了一个**聪明的设计**：
1. **内部统一表示**：所有工具都统一转换为 OpenAI 函数调用格式（JSON Schema）
2. **自动供应商转换**：借助 LiteLLM 库自动将工具格式转换为不同提供商所需的格式
3. **无需手动处理**：开发者不需要为不同提供商编写不同的工具传递逻辑

---

## 详细分析

### 1️⃣ 工具定义流程

#### 1.1 工具从命令定义到函数调用格式

**文件**: `sweagent/tools/commands.py`

```python
class Command(BaseModel):
    """Represents an executable command with arguments and documentation"""
    name: str
    docstring: str | None
    arguments: list[Argument] = []
    
    def get_function_calling_tool(self) -> dict:
        """Converts this command into an OpenAI function calling tool definition"""
        tool = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.docstring or "",
                "parameters": {
                    "type": "object",
                    "properties": properties,  # 从 arguments 转换
                    "required": required        # 必需参数列表
                }
            }
        }
        return tool
```

**关键点**：
- 每个 `Command` 对象都有一个 `get_function_calling_tool()` 方法
- 返回格式遵循 **OpenAI 的函数调用 JSON Schema** 标准
- 所有工具都统一为这个格式，**与 LLM 提供商无关**

#### 1.2 工具配置集合

**文件**: `sweagent/tools/tools.py`

```python
class ToolConfig(BaseModel):
    """Configuration for the tools that are made available to the agent"""
    
    bundles: list[Bundle] = Field(default_factory=list)
    """The tool bundles to load"""
    
    parse_function: ParseFunction = Field(default_factory=FunctionCallingParser)
    """The action parser for parsing model output into thought and action"""
    
    @cached_property
    def commands(self) -> list[Command]:
        """Read command files and return parsed command objects"""
        commands = []
        # ... 从 bundles 加载命令 ...
        return commands
    
    @cached_property
    def tools(self) -> list[dict]:
        """Convert all commands to tool definitions"""
        return [command.get_function_calling_tool() for command in self.commands]
```

**关键点**：
- `ToolConfig.tools` 返回所有命令转换后的工具列表
- 所有工具都是统一的 OpenAI 格式
- 这是传给 LLM 的最终格式

---

### 2️⃣ 工具传给 LLM 的过程

#### 2.1 LiteLLMModel 类（统一模型接口）

**文件**: `sweagent/agent/models.py`

```python
class LiteLLMModel(AbstractModel):
    def __init__(self, args: GenericAPIModelConfig, tools: ToolConfig):
        self.config = args.model_copy(deep=True)
        self.tools = tools
        
        # 检查模型是否支持函数调用
        if tools.use_function_calling:
            if not litellm.utils.supports_function_calling(model=self.config.name):
                # 警告：该模型不支持函数调用
                self.logger.warning(f"Model {self.config.name} does not support function calling...")
        
        # 获取 LLM 提供商信息
        self.lm_provider = litellm.model_cost.get(self.config.name, {}).get(
            "litellm_provider", 
            self.config.name
        )
```

#### 2.2 核心查询方法（工具传递）

**文件**: `sweagent/agent/models.py`, 第 700-710 行

```python
def _single_query(
    self, messages: list[dict[str, str]], n: int | None = None, temperature: float | None = None
) -> list[dict]:
    """
    向 LLM 发送查询请求，并处理工具调用响应
    """
    # ... 其他处理 ...
    
    extra_args = {}
    if self.config.api_base:
        extra_args["api_base"] = self.config.api_base
    
    # ✨ 关键部分：工具传递
    if self.tools.use_function_calling:
        extra_args["tools"] = self.tools.tools  # 传递工具列表
    
    # ✨ 调用 litellm.completion()
    response = litellm.completion(
        model=self.config.name,
        messages=messages,
        temperature=self.config.temperature,
        top_p=self.config.top_p,
        api_version=self.config.api_version,
        api_key=self.config.choose_api_key(),
        **extra_args,
        **completion_kwargs,
        n=n,
    )
```

**关键点**：
- 传给 `litellm.completion()` 的 `tools` 参数是统一的 OpenAI 格式
- LiteLLM 自动处理格式转换
- 无需根据 `self.lm_provider` 进行条件分支

#### 2.3 响应解析（工具响应提取）

**文件**: `sweagent/agent/models.py`, 第 760-780 行

```python
def _single_query(self, ...) -> list[dict]:
    # ... litellm.completion() 调用 ...
    response = litellm.completion(...)
    
    # 处理响应
    for i in range(n_choices):
        output = choices[i].message.content or ""
        output_dict = {"message": output}
        
        # ✨ 工具调用响应提取
        if self.tools.use_function_calling:
            if response.choices[i].message.tool_calls:
                # LiteLLM 已经将响应标准化为统一格式
                tool_calls = [call.to_dict() for call in response.choices[i].message.tool_calls]
            else:
                tool_calls = []
            output_dict["tool_calls"] = tool_calls
        
        outputs.append(output_dict)
    
    return outputs
```

**关键点**：
- LiteLLM 的响应对象 `response.choices[i].message.tool_calls` 已经标准化
- 所有提供商的响应都被转换为同一格式
- 开发者无需关心底层提供商的具体格式

---

### 3️⃣ LiteLLM 的工具格式转换机制

#### 3.1 什么是 LiteLLM？

LiteLLM 是一个开源库，提供了对多个 LLM 提供商的统一接口：

```
┌─────────────────────────────────────────────────────┐
│          SWE-Agent (统一格式：OpenAI)                │
│          使用 litellm.completion()                   │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│          LiteLLM 库                                  │
│  (格式转换 + 提供商路由)                             │
└──────┬───────┬────────┬────────┬────────┬──────────┘
       │       │        │        │        │
       ▼       ▼        ▼        ▼        ▼
    OpenAI  Anthropic Google  Cohere  LocalLLM
    (native)(转换)    (转换)  (转换)  (转换)
```

#### 3.2 不同提供商的工具调用格式

虽然 SWE-Agent 内部统一使用 OpenAI 格式，但让我们看一下各提供商的实际需求：

| 提供商 | 工具定义格式 | 工具调用响应格式 | LiteLLM 处理 |
|--------|------------|----------------|------------|
| **OpenAI** | JSON Schema (function calling) | `tool_calls` 数组 | ✅ 原生支持 |
| **Anthropic (Claude)** | 使用 `tools` 参数，类似 JSON Schema | `tool_use` 块 | ✅ 转换为标准格式 |
| **Google (Gemini)** | `tools` 参数，JSON Schema | `functionCalls` 数组 | ✅ 转换为标准格式 |
| **Cohere** | `tools` 参数，JSON 格式 | `tool_calls` 对象 | ✅ 转换为标准格式 |
| **本地模型** | 取决于模型后端 | 取决于模型后端 | ⚠️ 需要配置 |

#### 3.3 LiteLLM 在代码中的作用

**文件**: `sweagent/agent/models.py`

```python
import litellm

# 初始化时检查模型是否支持函数调用
if tools.use_function_calling:
    if not litellm.utils.supports_function_calling(model=self.config.name):
        # 给用户警告
        logger.warning(f"Model {self.config.name} does not support function calling...")

# 获取提供商信息（用于成本计算等）
self.lm_provider = litellm.model_cost.get(self.config.name, {}).get("litellm_provider")

# 关键：直接传统一格式的工具，LiteLLM 自动转换
response = litellm.completion(
    model=self.config.name,
    tools=self.tools.tools,  # 统一的 OpenAI 格式
    # ... 其他参数 ...
)
```

---

### 4️⃣ 工具调用解析流程

#### 4.1 三种解析模式

**文件**: `sweagent/tools/parsing.py`

SWE-Agent 支持多种工具调用解析器：

```python
# 1. 函数调用解析器（native tool calling）
class FunctionCallingParser(AbstractParseFunction, BaseModel):
    """Expects the model response to be a LiteLLM tool call"""
    type: Literal["function_calling"] = "function_calling"
    
    def __call__(self, model_response: dict, commands: list[Command]):
        tool_calls = model_response.get("tool_calls", None)
        # ... 验证和解析工具调用 ...
        action = self._parse_tool_call(tool_call, commands)
        return message, action

# 2. XML 函数调用解析器
class XMLFunctionCallingParser(AbstractParseFunction, BaseModel):
    """Expects the model response to be a tool calling format in XML tags"""
    type: Literal["xml_function_calling"] = "xml_function_calling"
    
    def __call__(self, model_response: dict, commands: list[Command]):
        # 从 XML 标签中解析函数调用
        # <function=bash>
        # <parameter=command>ls</parameter>
        # </function>
        # ...

# 3. 文本格式解析器（备选方案）
class ThoughtActionParser(AbstractParseFunction, BaseModel):
    """Expects response to be discussion followed by command wrapped in backticks"""
    type: Literal["thought_action"] = "thought_action"
    
    def __call__(self, model_response: dict, commands: list[Command]):
        # 从 ``` 代码块中解析命令
```

#### 4.2 工具调用验证

**FunctionCallingParser._parse_tool_call** 方法：

```python
def _parse_tool_call(self, tool_call: dict, commands: list[Command]):
    """
    解析 LiteLLM 标准化的工具调用响应
    """
    name = tool_call["function"]["name"]
    command = {c.name: c for c in commands}.get(name)
    
    if not command:
        raise FunctionCallingFormatError(f"Command '{name}' not found")
    
    # 解析 JSON 参数
    if not isinstance(tool_call["function"]["arguments"], dict):
        values = json.loads(tool_call["function"]["arguments"])
    
    # 验证必需参数
    required_args = {arg.name for arg in command.arguments if arg.required}
    missing_args = required_args - values.keys()
    if missing_args:
        raise FunctionCallingFormatError(f"Required argument(s) missing: {missing_args}")
    
    # 验证额外参数
    valid_args = {arg.name for arg in command.arguments}
    extra_args = set(values.keys()) - valid_args
    if extra_args:
        raise FunctionCallingFormatError(f"Unexpected argument(s): {extra_args}")
    
    # 格式化参数
    formatted_args = {
        arg.name: Template(arg.argument_format).render(value=get_quoted_arg(values[arg.name]))
        for arg in command.arguments
        if arg.name in values
    }
    
    return command.invoke_format.format(**formatted_args).strip()
```

---

### 5️⃣ 差异化处理分析

#### 5.1 是否有针对不同提供商的差异化处理？

**答案：最小化的差异化处理**

##### 仅有的明确差异处理：

1️⃣ **Anthropic Claude 模型的最大输出令牌处理**

**文件**: `sweagent/agent/models.py`, 第 600-620 行

```python
def __init__(self, args: GenericAPIModelConfig, tools: ToolConfig):
    # ... 其他初始化 ...
    
    if self.config.max_output_tokens is not None:
        self.model_max_output_tokens = self.config.max_output_tokens
    else:
        self.model_max_output_tokens = litellm.model_cost.get(self.config.name, {}).get("max_output_tokens")
        
        # ✨ 针对 Claude 的特殊处理
        is_claude_3_7 = "claude-3-7-sonnet" in self.config.name or "claude-sonnet-4" in self.config.name
        has_128k_beta_header = (
            self.config.completion_kwargs.get("extra_headers", {}).get("anthropic-beta") 
            == "output-128k-2025-02-19"
        )
        if is_claude_3_7 and not has_128k_beta_header:
            self.model_max_output_tokens = 64000  # 默认 64k
            self.logger.warning(
                "Claude 3.7/4 models do not support 128k context by default. "
                "Setting max output tokens to 64k..."
            )
```

2️⃣ **Anthropic 模型的 max_tokens 必需参数**

**文件**: `sweagent/agent/models.py`, 第 707-711 行

```python
completion_kwargs = self.config.completion_kwargs
if self.lm_provider == "anthropic":
    # ✨ Anthropic 需要显式设置 max_tokens
    completion_kwargs["max_tokens"] = self.model_max_output_tokens
```

3️⃣ **系统消息转换（针对不支持系统消息的模型）**

**文件**: `sweagent/agent/models.py`, 第 90-105 行

```python
class GenericAPIModelConfig(PydanticBaseModel):
    convert_system_to_user: bool = False
    """Whether to convert system messages to user messages. This is useful for
    models that do not support system messages like o1.
    """
```

#### 5.2 工具定义的转换由 LiteLLM 负责

SWE-Agent **本身不处理** 工具定义格式的转换，全部委托给 LiteLLM：

```python
# ❌ SWE-Agent 中不存在这样的代码：
if self.lm_provider == "anthropic":
    tools = convert_to_anthropic_format(tools)
elif self.lm_provider == "google":
    tools = convert_to_google_format(tools)
elif self.lm_provider == "openai":
    # 保持原样
    pass

# ✅ 实际代码：
response = litellm.completion(
    model=self.config.name,
    tools=self.tools.tools,  # 直接传递统一格式
    # ... 其他参数 ...
)
```

---

### 6️⃣ 支持的工具调用方案对比

SWE-Agent 支持多种工具交互方案，可根据模型能力选择：

| 方案 | 解析器 | 适用场景 | 示例模型 |
|------|--------|---------|---------|
| **Native Function Calling** | `FunctionCallingParser` | 模型原生支持工具调用 | GPT-4, Claude 3.5, Gemini 2.0 |
| **XML Function Calling** | `XMLFunctionCallingParser` | 模型倾向于 XML 格式 | Sonnet 3, 某些开源模型 |
| **Thought + Action** | `ThoughtActionParser` | 降级方案，纯文本 | 任何模型 |
| **JSON 格式** | `JsonParser` | 结构化 JSON 输出 | 支持 JSON 输出的模型 |
| **代码块格式** | `BashCodeBlockParser` | 执行 bash 代码块 | 任何模型 |

---

## 7️⃣ 完整调用流程示意图

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Agent Step 初始化                                            │
│    - 加载 ToolConfig                                            │
│    - 所有命令转为 OpenAI 格式的工具定义                          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. LiteLLMModel.query()                                         │
│    - 准备消息列表                                               │
│    - 收集 self.tools.tools（OpenAI 格式）                        │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. litellm.completion()                                         │
│    model = "gpt-4"/"claude-3-5-sonnet"/"gemini-2.0" etc        │
│    tools = [OpenAI JSON Schema 格式]                            │
│                                                                 │
│    LiteLLM 内部：                                               │
│    - 检测 model 对应的提供商                                    │
│    - 将工具定义转换为该提供商的格式                             │
│    - 发送 API 请求                                             │
│    - 接收并标准化响应                                          │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. 响应返回（LiteLLM 标准化）                                   │
│    response.choices[i].message.tool_calls = [                  │
│      {                                                          │
│        "type": "function",                                      │
│        "id": "call_xxx",                                        │
│        "function": {                                            │
│          "name": "command_name",                                │
│          "arguments": "{...}"  # JSON 字符串或字典             │
│        }                                                        │
│      }                                                          │
│    ]                                                            │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. SWE-Agent 解析响应                                           │
│    - FunctionCallingParser._parse_tool_call()                  │
│    - 验证工具名称和参数                                        │
│    - 将参数格式化为 shell 命令                                 │
│    返回: (thought, action)                                      │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. 执行命令                                                     │
│    - 在环境中执行 action                                        │
│    - 收集输出作为 observation                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8️⃣ 配置示例对比

### 使用函数调用（推荐）

```yaml
# config/default.yaml
agent:
  model:
    name: "gpt-4"
  tools:
    parse_function:
      type: function_calling  # ✨ 启用原生工具调用
    enable_bash_tool: true
```

**工作流**：
1. 工具通过函数调用方式传递给 LLM
2. LLM 返回 `tool_calls` 响应
3. `FunctionCallingParser` 解析并执行

### 使用文本格式（降级）

```yaml
agent:
  model:
    name: "some-limited-model"
  tools:
    parse_function:
      type: thought_action  # 不使用函数调用
    enable_bash_tool: true
```

**工作流**：
1. 系统提示中包含工具文档（通过 `{{command_docs}}`）
2. LLM 返回纯文本（思考 + 代码块中的命令）
3. `ThoughtActionParser` 解析代码块并执行

---

## 9️⃣ 关键设计决策分析

### 为什么这样设计很聪明？

#### ✅ **优点**

1. **可维护性高**：新增 LLM 提供商时，只需更新 LiteLLM，无需修改 SWE-Agent
2. **代码清晰**：没有充满条件分支的 `if provider == "xxx"` 代码
3. **灵活性强**：支持多种解析方案，可根据模型能力动态选择
4. **成本效益好**：减少了 SWE-Agent 的维护负担
5. **向后兼容**：即使某个模型不支持函数调用，也可切换到其他解析器

#### ⚠️ **权衡**

1. **依赖性**：强依赖于 LiteLLM 的正确实现
2. **错误诊断**：工具格式错误时，难以定位是 SWE-Agent 还是 LiteLLM 的问题
3. **定制化有限**：如果需要非常特殊的工具格式处理，可能需要修改 LiteLLM

---

## 🔟 总结对比表

| 维度 | 实现方式 | 说明 |
|------|---------|------|
| **工具定义格式** | 统一为 OpenAI JSON Schema | 所有命令都转为标准格式 |
| **格式转换** | 由 LiteLLM 负责 | SWE-Agent 不参与格式转换 |
| **提供商差异处理** | 极少（仅 Anthropic 特例） | 大部分通过 LiteLLM 透明处理 |
| **工具调用解析** | 支持多种解析器 | 可根据模型能力灵活选择 |
| **响应标准化** | LiteLLM 负责 | 所有提供商响应统一为一个格式 |
| **扩展新提供商** | 更新 LiteLLM 配置 | 无需修改 SWE-Agent 代码 |

---

## 源代码关键位置速查表

| 功能 | 文件 | 行数 | 说明 |
|------|------|------|------|
| 工具定义 | `sweagent/tools/commands.py` | 1-250 | Command 和 Argument 类 |
| 工具转换 | `sweagent/tools/commands.py` | 150-180 | `get_function_calling_tool()` |
| 工具收集 | `sweagent/tools/tools.py` | 200-220 | ToolConfig.tools 属性 |
| 工具传递 | `sweagent/agent/models.py` | 700-715 | `_single_query()` 方法 |
| 响应提取 | `sweagent/agent/models.py` | 760-780 | 工具调用响应处理 |
| 工具解析 | `sweagent/tools/parsing.py` | 371-455 | `FunctionCallingParser` 类 |
| 参数验证 | `sweagent/tools/parsing.py` | 400-450 | `_parse_tool_call()` 方法 |
| 提供商处理 | `sweagent/agent/models.py` | 600-625, 707-711 | Anthropic 特殊处理 |

---

## 📚 补充信息

### 支持的 LLM 提供商列表（通过 LiteLLM）

- ✅ **OpenAI**: GPT-4, GPT-4 Turbo, GPT-4o
- ✅ **Anthropic**: Claude 3 Opus/Sonnet/Haiku, Claude 4
- ✅ **Google**: Gemini 1.5 Pro/Flash, Gemini 2.0
- ✅ **Cohere**: Command R, Command R+
- ✅ **Mistral**: Mistral Large, Mixtral
- ✅ **本地模型**: LLaMA, Vicuna 等（通过 Ollama/vLLM）
- ✅ **其他**: Azure OpenAI, Replicate, Together AI 等

### 相关文档链接

- LiteLLM 官方文档：https://docs.litellm.ai/
- SWE-Agent FAQ：https://swe-agent.com/latest/faq/
- OpenAI 函数调用：https://platform.openai.com/docs/guides/function-calling

---

**分析完成时间**: 2025年12月12日  
**分析范围**: SWE-Agent 主分支 (MAS)  
**关键版本**: v0.7+ (当前最新)
