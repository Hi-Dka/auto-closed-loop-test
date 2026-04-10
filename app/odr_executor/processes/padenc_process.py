import os

from PIL import Image, ImageDraw, ImageFont

from app.odr_executor.core.logger import base_log, TaskLoggerAdapter
from app.odr_executor.core.guard import ProcessGuard
from typing import Any


def generate_image(
    data_text,
    bg_color,
    text_color="white",
    img_x=300,
    img_y=300,
    output_dir="/tmp/generated_images",
    filename="slide.png",
):
    image = Image.new("RGBA", (img_x, img_y), bg_color)
    draw = ImageDraw.Draw(image)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    font_size = 40

    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        font = ImageFont.load_default()

    left, top, right, bottom = draw.textbbox((0, 0), data_text, font=font)
    text_width = right - left
    text_height = bottom - top

    x = (img_x - text_width) / 2 - left
    y = (img_y - text_height) / 2 - top

    draw.text((x, y), data_text, fill=text_color, font=font)

    filepath = os.path.join(output_dir, filename)

    image.save(filepath, "PNG")


class PadEncGuard(ProcessGuard):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"PadEnc-{task_id}")
        self._base_cmd = ["odr-padenc"]
        self._log = TaskLoggerAdapter(base_log, {"tag": self.tag})
        self._task_id = task_id

    def _parse_command(self, cmd: dict[str, Any]) -> list[str]:

        self._log.info("parsing command for pad encoder...")

        if "sleep" not in cmd:
            self._log.warning(
                "Sleep time not specified in new command, using default value: 10"
            )
            cmd["sleep"] = 10

        if "dir" not in cmd:
            self._log.warning(
                f"Directory not specified in new command, using default value: /config/padenc/slides-{self.tag}"
            )
            cmd["dir"] = f"/media/padenc/sls-{self.tag}"

        if "dls" not in cmd:
            self._log.warning(
                f"DLS not specified in new command, using default value: /config/padenc/dls-{self.tag}/dls.txt"
            )
            cmd["dls"] = f"/media/padenc/dls-{self.tag}/dls.txt"
            os.makedirs(f"/media/padenc/dls-{self.tag}", exist_ok=True)
            with open(cmd["dls"], "w", encoding="utf-8") as f:
                f.write(self.tag)

        os.makedirs(cmd["dir"], exist_ok=True)
        if not os.listdir(cmd["dir"]):
            generate_image(
                data_text=self.tag,
                bg_color="white",
                text_color="red",
                img_x=320,
                img_y=240,
                output_dir=cmd["dir"],
                filename=self._task_id + ".png",
            )

        dls_dir = os.path.dirname(cmd["dls"])
        if dls_dir:
            os.makedirs(dls_dir, exist_ok=True)

        if not os.path.exists(cmd["dls"]):
            with open(cmd["dls"], "w", encoding="utf-8") as f:
                f.write(self.tag)

        cmd_list = self._base_cmd + [
            "-d",
            str(cmd["dir"]),
            "-t",
            str(cmd["dls"]),
            "-s",
            str(cmd["sleep"]),
            "-o",
            f"{self.tag}.sock",
            "-v",
        ]

        return cmd_list
