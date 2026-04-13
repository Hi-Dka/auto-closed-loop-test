<h1 align="center">Script Documentation</h1>

## Adb 相关脚本
- [adb_server.bat](../script/adb_server.bat)：监控本地 adb server 的运行情况，解决连接不稳定，服务器执行了 adb kill-server 导致的本地不能重启 adb server 的问题。

- **注意**：在使用开发服务器情况下，通常需要修改 *ANDROID_ADB_SERVER_PORT* 环境变量的值，确保不会出现端口冲突的情况， 默认值为:5037。


## hook 相关脚本
- [pre_commit.py](../script/pre_commit.py)：编译测试程序，push到安卓开发板上，执行测试程序，获取测试结果。可以配合 git hook 实现每次提交代码前自动执行测试程序，确保代码质量。具体配置方法可以参考[点击这里](./git-hooks-setup.md)

- **Python脚本需要根据个人环境进行配置，甚至修改**