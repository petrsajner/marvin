"""The tool that makes a picture, when the owner has allowed it.

Registered only when the setting is on, so a model that cannot generate is never
told that it can - a tool in the schema is a promise, and an unkeepable one costs
a wasted step and a wrong answer to the user.
"""
from __future__ import annotations

from pathlib import Path

from harness import openart
from harness.i18n import t
from harness.tools.base import AgentContext, Risk, Tool, ToolRegistry

CATALOGUE = "\n".join("- %s: %s" % row for row in openart.MODELS)


class GenerateImageTool(Tool):
    name = "generate_image"
    description = (
        "Generate a picture from a description and save it in the current project. "
        "This is a paid call to an online service on the user's account, so use it "
        "when a picture is actually wanted - a game sprite, a texture, a mock-up, an "
        "illustration - and not to decorate an answer.\n\n"
        "Models, best first for general work:\n" + CATALOGUE + "\n\n"
        "Pass `reference` to edit or vary an existing picture instead of starting "
        "from nothing. Write a full, specific prompt: subject, style, framing, "
        "colours and background. The saved file path comes back and can be read "
        "with the image tools like any other file."
    )
    parameters = {
        "prompt": {"type": "string",
                   "description": "What the picture shows. Be specific and complete."},
        "model": {"type": "string",
                  "description": "Model id from the list above. Defaults to %s." % openart.DEFAULT_MODEL},
        "reference": {"type": "string",
                      "description": "Optional path to an existing image to edit or vary."},
        # Measured: the service names the file after its own id, so a folder of
        # these is unreadable without this.
        "name": {"type": "string",
                 "description": "File name stem for the saved picture, without the "
                                "extension. Always pass one that describes the picture: "
                                "the service otherwise names the file after its internal "
                                "id, like nA0WZVN7tMQTDSLq8sdx.png."},
    }
    required = ["prompt"]
    risk = Risk.WRITE             # It writes a file and spends the owner's credits.

    def run(self, ctx: AgentContext, prompt: str, model: str = "",
            reference: str = "", name: str = "") -> str:
        cfg = ctx.cfg
        if not openart.enabled(cfg):
            return "ERROR: " + t("Image generation is switched off in settings.")
        absent = openart.missing(cfg)
        if absent:
            return "ERROR: " + t("Image generation is not ready: {what}",
                                 what=", ".join(absent))
        target = ctx.project_workspace or ctx.workspace
        directory = Path(target) / openart.SAVE_DIRECTORY
        # An unlisted model is passed through rather than refused: the table in the
        # description is the short list worth knowing, not the whole of OpenArt, and
        # the service says plainly if it does not recognise one.
        chosen = (model or openart.DEFAULT_MODEL).strip()
        picture = None
        if reference:
            picture = ctx.resolve(reference)
            if not picture.is_file():
                return "ERROR: " + t("Reference image not found: {path}", path=reference)
        price = openart.cost(cfg, chosen)
        result = openart.generate(cfg, prompt, model=chosen,
                                  directory=directory, reference=picture)
        if not result.get("ok"):
            return "ERROR: " + str(result.get("error") or t("No picture came back."))
        files = result["files"]
        if name:
            renamed = []
            for index, path in enumerate(files):
                stem = name if len(files) == 1 else "%s-%d" % (name, index + 1)
                destination = path.with_name(stem + path.suffix)
                if destination != path and not destination.exists():
                    path.rename(destination)
                    path = destination
                renamed.append(path)
            files = renamed
        for path in files:
            ctx.pending_images.append(path)
            # The service writes the file itself, so nothing else would record it
            # and Results would never show a picture whose path is sitting in the
            # conversation.
            if ctx.changes is not None:
                ctx.changes.record_created(path)
        lines = [t("Generated with {model}: {files}", model=chosen,
                   files=", ".join(str(p) for p in files))]
        if price is not None:
            lines.append(t("Cost: {credits} credits.", credits=price))
        return "\n".join(lines)


def register_image_tools(reg: ToolRegistry) -> None:
    reg.register(GenerateImageTool())
