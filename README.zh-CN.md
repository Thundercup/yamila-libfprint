# Yamila Linux 指纹驱动

[English](README.md) · [下载发行包](https://github.com/Thundercup/yamila-libfprint/releases) · [详细支持矩阵](docs/SUPPORT.md)

面向 **USB `2808:06fc`、设备修订 `0x2003` 的 Yamila 指纹模块**的实验性社区驱动。通过私有 libfprint 后端连接发行版原生 **fprintd**，使用专用账户隔离算法进程。

- 支持通过标准 fprintd 客户端录入指纹和进行一对一验证。
- 软件包附带固定原厂算法二进制，无需从 Windows 提取文件，也无需安装 Wine。
- 保留系统 libfprint，只为 fprintd 加载本项目的私有库。
- 原厂算法运行于独立 worker，不加载到特权 fprintd 进程中。

当前版本是**社区测试版**。其他设备型号/修订、ARM、identify、跨手指重复录入检测和开机登录尚不在已验收范围内。

## 系统与软件包

| 系统 | 架构 | 软件包 | 认证接入 |
| --- | --- | --- | --- |
| Ubuntu 26.04 | amd64 | DEB | 首次配置时自动启用发行版指纹 PAM profile，保留密码认证及管理员后续选择 |
| Fedora 44 | x86_64 | RPM / SRPM | 私有库、专用账户及自有 SELinux 策略；保留现有 PAM/authselect 配置 |

已在 Fedora 44 和 Ubuntu 26.04 上完成部分功能测试，详细结果见[支持矩阵](docs/SUPPORT.md)。欢迎提交其他 x86_64 发行版的兼容性反馈。

## 安装

从[发行页面](https://github.com/Thundercup/yamila-libfprint/releases)下载对应软件包及 `SHA256SUMS`，安装前核对摘要。当前软件包未签名；摘要用于发现字节变化，不能代替签名身份。保留登录密码及旧驱动的恢复方法。

### Ubuntu 26.04

在下载目录执行：

```sh
sudo apt install ./yamila-libfprint_0.0.1-4ubuntu26.04_amd64.deb
sudo dpkg --verify yamila-libfprint
```

正常情况下第二条命令没有输出。标准托管 PAM 配置不需要另行启用指纹：安装程序通过发行版 `pam-auth-update` 启用指纹 profile，保留 Unix 密码认证和其他 profile，不强制覆盖本地修改。遇到冲突时配置步骤可能失败，需要先审阅原因。

如果之后希望关闭通用指纹认证，可执行：

```sh
sudo pam-auth-update --disable fprintd
```

该选择会在重配置时保留。指纹认证可能先等待超时，再进入密码提示。卸载时，仅撤销本包开启且之后配置未变化的指纹偏好；原来已启用或后来修改的配置保留。详见[Ubuntu 安装、回退与卸载说明](docs/UBUNTU.md)。

### Fedora 44

```sh
sudo dnf install ./yamila-libfprint-0.0.1-11.fc44.x86_64.rpm
rpm -V yamila-libfprint
```

软件包安装自有 SELinux 模块和精确 USB 权限规则，不自动修改 PAM/authselect。迁移前请阅读[Fedora 安装与恢复指南](packaging/INSTALL.md)，核对依赖、冲突和旧驱动恢复路径。

## 录入和验证

安装及设备识别正常后，可以使用 GNOME/KDE 设置，或标准客户端：

```sh
fprintd-list "$USER"
fprintd-enroll -f right-index-finger "$USER"
fprintd-verify -f right-index-finger "$USER"
```

后两条命令会立即请求触摸。其他驱动的加密模板不会自动转换，准备好后再录入新的原生模板。RAW FpPrint 没有额外的驱动层加密，访问保护依赖系统存储权限；请保持密码认证可用。

## 构建与测试

按照[Fedora 构建说明](packaging/INSTALL.md#build)或[Ubuntu 构建说明](docs/UBUNTU.md#build)安装依赖，以普通用户执行：

```sh
python3 -B tools/audit.py
python3 -B tools/release_check.py
python3 -B tools/build.py --fetch-upstream --test-mode
python3 -B tools/check.py
```

[上游 libfprint](upstream.lock.json)固定版本和 SHA-256。默认测试使用合成数据，测试构建不能用于安装。GitHub Actions 运行合成检查，分别构建 Fedora RPM/SRPM 和 Ubuntu DEB；不访问 USB，也不执行原厂 DLL。构建产物包含对应源码、构建记录和校验值。

## 许可与原厂组件

项目自行编写的源码采用 **LGPL-2.1-or-later**。附带的 `YmlWbioEngineAdapter.dll` 是独立的**原厂专有 Windows x64 二进制**，由 Linux 兼容 worker 执行，不属于本项目开源许可，也不代表算法已经开源或重新编译为 Linux 库。请阅读[来源说明](NOTICE.md)、[LGPL 原文](LICENSES/LGPL-2.1-or-later.txt)和[原厂组件声明](vendor/LICENSE-NOTICE.md)。

## 问题反馈

提交问题时请提供系统/软件包版本和最小错误描述。更多信息见[排错指南](docs/TROUBLESHOOTING.md)及[贡献说明](CONTRIBUTING.md)。不要在 issue 中上传指纹图像、模板、密钥、密码或原始 USB 抓包。
