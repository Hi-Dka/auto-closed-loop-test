<h1 align="center">Miniconda Installation Guide</h1>

因为在开发服务器上的软件比如CMake，Python等的版本较旧，但又没有安装软件的权限，无法满足测试需求，所以需要安装Miniconda来管理软件环境。

## 下载Miniconda安装脚本
```bash
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
```

## 安装Miniconda
```bash
bash Miniconda3-latest-Linux-x86_64.sh
```

## 使用帮助
```bash
conda --help
```

## 注意事项
正常情况下不要使用base环境，建议创建一个新的环境来安装需要的软件包，以避免与系统环境发生冲突。