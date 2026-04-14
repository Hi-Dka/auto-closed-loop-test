<h1 align="center">Auto Closed Loop Test</h1>

## 简要说明

- `odr_executor`：负责管理 ODR Tools 工具、 FFmpeg 以及 HackRf 设备。
- `scheduler`：负责调度测试流程，执行测试套件中的测试用例，并可以通过接口控制 ODR Executor。

**为了方便测试和开发，建议在本地环境中运行 ODR Executor 和 Scheduler**。

因为开发服务器不是本地，无法直接访问本地服务和本地连接的开发板，可以通过 SSH 隧道的方式将本地服务暴露到开发服务器上，然后利用 adb 的 C/S 架构，以及端口转发功能实现测试程序和本地服务,开发服务器的互通。windows 设备建议使用bat脚本监控本地 adb server 的运行情况,以解决连接不稳定，服务器执行了 adb kill-server 导致的本地不能重启 adb server 的问题。