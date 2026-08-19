# 蜘蛛侠Spiderman+V1.3

## V1.3 简要说明

- 目标：Windows 下可配置步骤的轻量自动化执行工具。
- 执行模型：按步骤顺序执行，支持循环 `K` 次和步骤间延迟。
- 任务承载：JSON 文件，可保存、加载、导出复用。
- 步骤类型：`click`、`paste`、`key`、`wait`。

一个面向 Windows 的轻量自动化任务工具。

## 特点

- 用 Tkinter 做桌面 UI，依赖少
- 任务用 JSON 保存，方便复用和内网分发
- 支持循环执行 K 次
- 支持步骤间隔 delay，默认 0.3 秒
- 支持 4 类步骤：
  - 点击：`x`, `y`, `button`
  - 粘贴：JSON 数组文本，逐条复制粘贴
  - 键盘：`tab`、`shift+tab`、`ctrl+c`、`ctrl+shift+s` 这类组合
  - 等待：秒数

## 任务格式

```json
{
  "version": 1,
  "name": "demo",
  "loop_count": 3,
  "delay_seconds": 0.3,
  "steps": [
    { "type": "click", "x": 100, "y": 200, "button": "left" },
    { "type": "paste", "items": ["hello", "world"] },
    { "type": "key", "combo": "ctrl+v" },
    { "type": "wait", "seconds": 1 }
  ]
}
```

## 运行

```bash
D:/Anaconda/python.exe app.py
```

## 依赖安装

```bash
D:/Anaconda/python.exe -m pip install -r requirements.txt
```

## 打包建议

如果后面要做成内网可分发的单文件程序，可以直接用 PyInstaller：

```bash
D:/Anaconda/python.exe -m pip install pyinstaller
D:/Anaconda/python.exe -m PyInstaller --noconsole --onefile app.py
```

## 一键发布产物

项目内置了 [build.py](build.py)（V1.3 发布脚本）：

- 生成单文件 exe
- 打包 zip（文件名示例：spiderman_v1.3.zip）
- 按 48MB 切片到 `parts/`

执行：

```bash
.venv/Scripts/python.exe build.py
```

切片合并（Windows PowerShell）：

```powershell
$parts = Get-ChildItem .\parts\spiderman.zip.part* | Sort-Object Name
$target = ".\spiderman.zip"
$ms = New-Object System.IO.MemoryStream
foreach ($p in $parts) {
  $bytes = [System.IO.File]::ReadAllBytes($p.FullName)
  $ms.Write($bytes, 0, $bytes.Length)
}
[System.IO.File]::WriteAllBytes($target, $ms.ToArray())
$ms.Dispose()
```
