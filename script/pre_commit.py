"""
# -*- coding: utf-8 -*-
"""

import os
from typing import Any, Dict, cast
import subprocess
import asyncio

import requests
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel


# -------------------------------- environment ------------------------------- #
ANDROID_NDK_HOME = "/home/yangxinxin/Android/android-ndk-r27d"
CMAKE_LAUNCHER = "ccache"
# -------------------------------- environment ------------------------------- #

# ---------------------------- cmake configuration --------------------------- #
SOURCE_DIR = (
    "/home/yangxinxin/Project/BAIC_3B2525/lagvm/lagvm/LINUX/android/"
    "vendor/common/services/RadioHal/radio"
)

CMAKE_CONFIG_PRESET = "Android_Radio_Test_Configure"
CMAKE_BUILD_PRESET = "Android_Radio_Test_Build"
# ---------------------------- cmake configuration --------------------------- #

# ------------------------- executable configuration ------------------------- #
EXECUTABLE_PATH = "/home/yangxinxin/Project/BAIC_3B2525/lagvm/lagvm/LINUX/android/vendor/common/services/RadioHal/radio/build/Android_Radio_Test/bin/test_c_dab_session"
# ------------------------- executable configuration ------------------------- #

# -------------------------- scheduler configration -------------------------- #
SCHEDULE_SERVER_URL = "http://localhost:8090"
# -------------------------- scheduler configration -------------------------- #

# ----------------------------- adb configration ----------------------------- #
FORWARD_PORT = 8000  # test_executor server port
RESERVE_PORT = 8090  # scheduler server port
ADB_SERVER_PORT = 5037
# ----------------------------- adb configration ----------------------------- #


console = Console()


def compile_code():
    """
    Compile the code using CMake with the specified presets and environment variables.
    """
    print(f"Compiling code with NDK at {ANDROID_NDK_HOME}...")
    print(f"Using CMake launcher: {CMAKE_LAUNCHER}")
    print(f"Source directory: {SOURCE_DIR}")
    print(f"CMake configure preset: {CMAKE_CONFIG_PRESET}")
    print(f"CMake build preset: {CMAKE_BUILD_PRESET}")

    env = os.environ.copy()

    env["ANDROID_NDK_HOME"] = ANDROID_NDK_HOME
    env["CMAKE_LAUNCHER"] = CMAKE_LAUNCHER
    env["ANDROID_ADB_SERVER_PORT"] = str(ADB_SERVER_PORT)

    print("Running CMake configure...")
    subprocess.run(
        [
            "cmake",
            "--preset",
            CMAKE_CONFIG_PRESET,
            "-S",
            SOURCE_DIR,
        ],
        cwd=SOURCE_DIR,
        env=env,
        check=True,
    )

    print("Running CMake build...")
    subprocess.run(
        [
            "cmake",
            "--build",
            "--preset",
            CMAKE_BUILD_PRESET,
            "-S",
            SOURCE_DIR,
        ],
        cwd=SOURCE_DIR,
        env=env,
        check=True,
    )


async def push_executable():
    """
    Push the compiled executable to the target device using ADB.
    """
    p = await asyncio.create_subprocess_exec(
        "adb",
        "forward",
        f"tcp:{FORWARD_PORT}",
        f"tcp:{FORWARD_PORT}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _, stderr = await p.communicate()
    if p.returncode != 0:
        print(f"Failed to set up port forwarding: {stderr.decode().strip()}")
        return

    p = await asyncio.create_subprocess_exec(
        "adb",
        "reverse",
        f"tcp:{RESERVE_PORT}",
        f"tcp:{RESERVE_PORT}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await p.communicate()
    if p.returncode != 0:
        print(f"Failed to set up port forwarding: {stderr.decode().strip()}")
        return

    print("Pushing executable to target device...")
    p = await asyncio.create_subprocess_exec(
        "adb",
        "push",
        EXECUTABLE_PATH,
        "/data/local/tmp/",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _, stderr = await p.communicate()
    if p.returncode != 0:
        print(f"Failed to push executable: {stderr.decode().strip()}")
        return

    print("Setting executable permissions...")
    p = await asyncio.create_subprocess_exec(
        "adb",
        "shell",
        "chmod",
        "+x",
        f"/data/local/tmp/{EXECUTABLE_PATH.rsplit('/',maxsplit=1)[-1]}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    _, stderr = await p.communicate()
    if p.returncode != 0:
        print(f"Failed to set executable permissions: {stderr.decode().strip()}")
        return

    print("Run executable on target device...")
    p = await asyncio.create_subprocess_exec(
        "adb",
        "shell",
        f"/data/local/tmp/{EXECUTABLE_PATH.rsplit('/',maxsplit=1)[-1]}",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    return p
    # _, stderr = await p.communicate()
    # if p.returncode != 0:
    #     print(f"Failed to run executable: {stderr.decode().strip()}")
    #     return


def get_schedule_status() -> dict[str, Any]:
    """
    Get the schedule status from the server and print it.
    """
    response = requests.post(
        f"{SCHEDULE_SERVER_URL}/control/v1/status",
        headers={"accept": "application/json"},
        data="",
        timeout=5,
    )
    response.raise_for_status()

    return cast(dict[str, Any], response.json())


async def check_schedule_status():
    """
    Check the schedule status and print it.
    """
    is_first_check = True
    is_after_running = False
    frame_idx = 0
    final_run_status = "unknown"
    final_last_outcome = "unknown"
    try:
        with Live(
            Panel("[yellow]Waiting for scheduler...[/yellow]", title="Scheduler"),
            console=console,
            refresh_per_second=12,
            transient=True,
        ) as live:
            while True:
                status = get_schedule_status()

                scheduler_running: bool | str = status.get(
                    "scheduler_running", "unknown"
                )
                scheduler_status = status.get("scheduler_status", "unknown")

                run_status = status.get("flow_status", {}).get("run_status", "unknown")

                last_outcome = status.get("last_outcome", "unknown")

                final_run_status = run_status
                final_last_outcome = last_outcome

                if isinstance(scheduler_running, str):
                    live.update(
                        Panel(
                            "[red]Scheduler running status is unknown.[/red]",
                            title="Scheduler",
                            border_style="red",
                        )
                    )
                    break

                if not scheduler_running:
                    if is_first_check:
                        live.update(
                            Panel(
                                "[yellow]Schedule is idle, waiting to start...[/yellow]",
                                title="Scheduler",
                            )
                        )
                        is_first_check = False

                    if is_after_running:
                        live.update(generate_step_view(status, frame_idx))
                        break

                    await asyncio.sleep(0.5)
                    continue

                if scheduler_status in {"initialized", "running"}:
                    is_after_running = True
                    live.update(generate_step_view(status, frame_idx))
                    frame_idx += 1
                    await asyncio.sleep(0.2)
                    continue

                live.update(generate_step_view(status, frame_idx))
                frame_idx += 1
                await asyncio.sleep(0.2)

        if final_run_status == "failed":
            print("Test failed. Please check the scheduler logs for more details.")
        elif final_last_outcome == "success":
            print("Schedule completed successfully!")
        elif final_last_outcome not in {"unknown", "idle"}:
            print(f"Schedule finished with outcome: {final_last_outcome}")

    except requests.RequestException as e:
        print(f"Failed to get schedule status: {e}")


def generate_step_view(data: Dict[str, Any], frame_idx: int):
    flow = data.get("flow_status", {})
    steps = flow.get("all_steps", [])
    current_id = flow.get("current_step_id")
    failed_id = flow.get("failed_step_id")
    run_status = flow.get("run_status", "unknown")

    spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    spinner = (
        f"[bold cyan]{spinner_frames[frame_idx % len(spinner_frames)]}[/bold cyan]"
    )

    table = Table.grid(padding=(0, 1))
    table.add_column("Status", justify="center", width=3)
    table.add_column("Step")

    if not steps:
        table.add_row("[grey]○[/grey]", "[grey50]No steps[/grey50]")
        return Panel(
            table,
            title="[bold blue]Pipeline Steps[/bold blue]",
            border_style="blue",
            expand=False,
        )

    current_idx = -1
    failed_idx = -1
    for i, s in enumerate(steps):
        if s.get("id") == current_id:
            current_idx = i
        if s.get("id") == failed_id:
            failed_idx = i

    for i, step in enumerate(steps):
        step_name = str(step.get("name", step.get("id", "unknown-step")))

        if failed_idx >= 0:
            if i < failed_idx:
                status_icon = "[bold green]●[/bold green]"
                style = "green"
            elif i == failed_idx:
                status_icon = "[bold red]✘[/bold red]"
                style = "bold red"
            else:
                status_icon = "[grey]○[/grey]"
                style = "grey50"
        elif run_status == "success":
            status_icon = "[bold green]●[/bold green]"
            style = "green"
        elif current_idx >= 0 and run_status in {"running", "initialized"}:
            if i < current_idx:
                status_icon = "[bold green]●[/bold green]"
                style = "green"
            elif i == current_idx:
                status_icon = spinner
                style = "bold cyan"
            else:
                status_icon = "[grey]○[/grey]"
                style = "grey50"
        elif run_status == "failed" and current_idx >= 0 and i == current_idx:
            status_icon = "[bold red]✘[/bold red]"
            style = "bold red"
        else:
            status_icon = "[grey]○[/grey]"
            style = "grey50"

        table.add_row(status_icon, f"[{style}]{step_name}[/{style}]")

    return Panel(
        table,
        title="[bold blue]Pipeline Steps[/bold blue]",
        border_style="blue",
        expand=False,
    )


async def main():
    compile_code()
    process = await push_executable()
    try:
        await check_schedule_status()
    finally:
        if process and process.returncode is None:
            process.terminate()
            await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
