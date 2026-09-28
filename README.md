# 华农课表转 ICS

作者：zeta

登录华南农业大学教务系统（默认 `jwzf` 正方版），自动下载个人课表并生成 `.ics` 日历文件，可直接导入手机或电脑日历（Apple 日历、Google 日历、Outlook、小米日历等）。

程序只使用 Python 标准库，不需要安装任何第三方依赖。账号密码只在本机使用，不会上传到任何第三方服务器。在校学生会自动走学校“统一身份认证”（融合门户 CAS）登录，不需要手动去网页点登录。

## 功能特性

- 自动通过学校统一身份认证登录 `jwzf` 正方教务系统，无需手动登录网页
- 自动抓取个人课表并按周展开，正确处理单双周课程
- 按学校 2026-2027 学年官方作息表生成每节课的起止时间
- 网页版提供日历选择器，日期自动填好，也可以手动选择其他开学日期
- 生成的 `.ics` 可直接导入 Apple 日历、Google 日历、Outlook、小米日历等
- 提供命令行版、网页版和 Tampermonkey 油猴脚本三种使用方式
- 账号密码只在本地内存中使用，不写入任何文件、不上传第三方服务器

## 环境要求

- Windows、macOS 或 Linux
- Python 3.9 或更高版本
- 能打开教务系统 `https://jwzf.scau.edu.cn` 的网络（校园网或 VPN）

## 使用方法

### 方式一：命令行（推荐）

在项目目录打开命令行，运行：

```bash
python scau_ics.py fetch
```

按提示输入学号和密码。在校学生账号会自动通过统一身份认证登录，不需要验证码。

首次使用 jwzf 版时不需要手动填写日期，程序会自动按校历推算“本学期第 1 周周一”的日期，例如 `2026-08-31`。运行结束后会在当前目录生成类似 `学号_2026-2027-1课表.ics` 的文件。

如果还要使用 jwxt 新版教务系统，运行 `python scau_ics.py fetch --source jwxt` 即可。

Windows 用户也可以直接双击：

- `启动命令行版.bat`
- 或 `启动网页版.bat`

### 方式二：网页版

```bash
python scau_ics.py serve
```

浏览器会自动打开 `http://127.0.0.1:8123`，在页面里选择 `jwzf 正方教务`，输入学号、密码即可，日期已经自动填好，也可以点击日历选择器修改，最后点击“生成课表文件”下载。遇到验证码时页面会直接显示图片。

### 方式三：备用转换模式

如果教务系统调整了接口导致自动抓取失败，可以用浏览器手动复制 JSON 再转换：

1. 用浏览器登录教务系统 `https://jwzf.scau.edu.cn`
2. 按 F12 打开开发者工具，切到 Network（网络）标签
3. 进入“我的选课 → 个人课表”
4. 在请求列表中找到名字包含 `xskbcx_cxXsgrkb` 的请求，右键 → Copy → Copy response，保存为 `timetable.json`
5. 运行：

```bash
python scau_ics.py convert --timetable-json timetable.json --start-date 2026-09-01
```

新版 jwxt 的备用转换仍然可用：`python scau_ics.py convert --calendar-json calendar.json --timetable-json timetable.json`。

### 方式四：浏览器油猴脚本（推荐在网页上直接导出）

也可以改用浏览器脚本，直接在教务系统页面里导出：

1. 在浏览器安装 Tampermonkey（油猴）扩展
2. 打开 [scau_ics.user.js](scau_ics.user.js)，Tampermonkey 会提示安装
3. 登录教务系统 `https://jwzf.scau.edu.cn`
4. 进入“我的选课 → 个人课表”，等课表加载完成后，点击页面右下角固定的“导出课表 ICS”按钮即可下载

## 其他参数

指定学期（例如 `2025-2026-1`）：

```bash
python scau_ics.py fetch --semester 2025-2026-1
```

也可以直接指定开学日期：

```bash
python scau_ics.py fetch --start-date 2026-08-31
```

保存接口原始 JSON 便于排查：

```bash
python scau_ics.py fetch --debug
```

更多帮助：

```bash
python scau_ics.py --help
```

## 打包 Windows exe

仓库不提交 exe 二进制文件，需要发布时自行打包或使用 GitHub Actions 自动构建。

本地打包：

```bash
python -m pip install -r requirements-dev.txt
python -m PyInstaller --noconfirm scau_ics.spec
```

打包完成后，exe 位于 `dist/华农课表导出.exe`。双击后会启动本地网页版，浏览器没自动打开时访问 `http://127.0.0.1:8123`。

如果使用 GitHub 仓库，推送一个 `v` 开头的标签（例如 `v3.0.0`）会自动触发 `.github/workflows/build-windows.yml`，构建 exe 并附加到对应的 Release 中。

## 项目结构

```text
.
├── scau_ics.py                     # 主程序：登录、抓取课表、生成 ICS、网页版
├── scau_ics.user.js                # Tampermonkey 油猴脚本
├── 启动命令行版.bat                # Windows 命令行启动器
├── 启动网页版.bat                  # Windows 网页版启动器
├── _get_python.cmd                 # 自动查找本机 Python
├── scau_ics.spec                   # PyInstaller 打包配置
├── requirements-dev.txt            # 打包所需依赖
├── README.md
├── LICENSE
└── .github/workflows/build-windows.yml
```

## 注意事项

- 不要在命令行参数里直接写密码（`--password`），Windows 下容易被历史记录保留；直接运行 `python scau_ics.py fetch` 后按提示输入即可。
- 登录过于频繁时教务系统会临时限制，请稍等再试。
- 如果密码已过期或首次登录，需要先到教务系统网页修改密码。
- 程序会自动按“第几周”展开每一节课，单双周课程也会正确处理。
- 如果自动抓取时提示 `/jwxtpt` 接口返回 `HTTP 404`，说明当前网络访问不到教务系统的课表服务（通常需要在校园网或校园 VPN 环境下才能访问）。此时请使用上面的“方式三：备用转换模式”，在能打开个人课表的浏览器里复制两个 JSON 再转换。

## 常见问题

- 双击 `启动命令行版.bat` 或 `启动网页版.bat` 后，窗口最后出现“Press any key to close this window”是正常的，按任意键后窗口才关闭，这是为了让你有时间看结果。程序成功时上方会显示“Done. The .ics file was saved into this folder.”，文件就保存在同一个文件夹里。
- 如果窗口显示“Found Python: python”，说明找到的是 Windows 商店的占位程序，不是真的 Python。新版启动脚本会自动跳过这种占位程序，优先使用 `C:\Users\你的用户名\Python313\python.exe`，不需要你手动处理。
- 如果窗口里只出现“Python was not found”，说明没有找到 Python。程序会自动查找 `C:\Users\你的用户名\Python313\python.exe`，把 Python 装到那里即可，不需要手动配置环境变量。
- 网页版启动后，如果没有自动打开浏览器，请手动访问 `http://127.0.0.1:8123`。不要同时开两个网页版，端口会被占用。
- 上课起止时间按华南农业大学 2026-2027 学年官方作息表生成（每节课 40 分钟，一天 15 节）。如果学校之后调整作息，需要同步更新程序里的作息表。

## 参考的开源项目

- [SCAU教务系统课表转换ICS工具](https://gitee.com/YelloooBlue/SCAU_Class2ICS)：华农校友 YelloooBlue 的 JSON 转 ICS 方案，本项目的课程字段整理和 ICS 生成规则参考了它。
- [ZhengFang-icsExporter](https://github.com/sdy623/ZhengFang-icsExporter)：正方教务系统课表抓取与转换的 Python 工具，本项目的 jwzf 课表接口参数和节次时间处理参考了它。

以上项目仅作为思路参考，本仓库不包含它们的源代码副本。

## 免责声明

- 本项目是个人学习与技术交流项目，与华南农业大学官方没有任何关系。
- 请仅使用自己的账号导出自己的课表，不要使用他人的账号或收集他人数据。
- 请合理控制请求频率，避免对学校教务系统造成额外压力。
- 教务系统和作息时间可能随时调整，若接口或时间发生变化，请自行修改代码适配。

## 开源协议

本项目使用 [MIT License](LICENSE) 开源。
