<h1 align="center">Git Hooks Setup</h1>

- 进入到项目根目录下的 .git/hooks 目录
- 将 pre-commit.sample 文件复制一份，并命名为 pre-commit
- 修改 pre-commit 文件内容为：

```bash
#!/bin/sh
python3 /path/to/pre_commit.py # 替换为 pre_commit.py 的实际路径
```