from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from importlib import import_module
from queue import Empty
from typing import Any

from . import theme
from ._geometry import (
    DEFAULT_GRID_COLUMNS,
    DEFAULT_GRID_GEOMETRY,
    DEFAULT_PIXEL_GEOMETRY,
    grid_cell_size,
    grid_to_pixels,
    move_grid_geometry,
    resize_grid_geometry,
)
from ._process_usage import ProcessUsage
from ._window_icon import apply_window_icon
from .deck import _DeckSettings

_logger = logging.getLogger(__name__)

_DEFAULT_PANEL_WIDTH = DEFAULT_PIXEL_GEOMETRY[2]
_DEFAULT_PANEL_HEIGHT = DEFAULT_PIXEL_GEOMETRY[3]
_DEFAULT_PANEL_GAP = 8
_MIN_PANEL_WIDTH = 120
_MIN_PANEL_HEIGHT = 80
_GEOMETRY_EVENT_DELAY_MS = 40
_PANEL_PADDING = 2
_PANEL_CORNER_RADIUS = 6
_PANEL_CONTENT_RADIUS = _PANEL_CORNER_RADIUS - 1
_PANEL_CORNER_SIZE = 12
_STATUS_BAR_HEIGHT = 24
_UNTITLED_BAR_HEIGHT = 8


def _bind_input_guard(frame: Any, is_disabled: Callable[[], bool]) -> None:
    """Block input before widget bindings without changing individual states."""
    tag = f"CardTableInputGuard:{frame}"

    def guard(_event: Any) -> str | None:
        return "break" if is_disabled() else None

    if not getattr(frame, "_cardtable_input_guard", False):
        for sequence in (
            "<ButtonPress>", "<ButtonRelease>", "<Motion>",
            "<KeyPress>", "<KeyRelease>", "<MouseWheel>",
        ):
            frame.bind_class(tag, sequence, guard)
        frame._cardtable_input_guard = True

    def bind_children(parent: Any) -> None:
        tags = parent.bindtags()
        if tag not in tags:
            parent.bindtags((tag, *tags))
        for child in tk.Misc.winfo_children(parent):
            bind_children(child)

    bind_children(frame)


def _bind_panel_activation(
    frame: Any, on_activate: Callable[[], None] | None = None
) -> None:
    """Raise and select a panel before its descendants handle input."""
    # Use a dedicated tag: reusing the frame's widget tag would also route
    # descendants' Configure events to CTkFrame's size tracking.
    tag = f"CardTablePanelActivation:{frame}"

    def activate(_event: Any) -> None:
        frame.lift()
        if on_activate is not None:
            on_activate()

    for sequence in ("<ButtonPress>", "<KeyPress>", "<MouseWheel>", "<FocusIn>"):
        frame.bind_class(tag, sequence, activate, add="+")

    def bind_children(parent: Any) -> None:
        # Run first even when an input's own binding returns "break".
        parent.bindtags((tag, *parent.bindtags()))
        # CTkFrame.winfo_children hides its internal canvas.
        for child in tk.Misc.winfo_children(parent):
            bind_children(child)

    bind_children(frame)


def _resolve_class(path: str) -> type:
    try:
        module_name, qualified_name = path.split(":", maxsplit=1)
    except ValueError as error:
        raise ValueError(
            f"Card class must use the 'package.module:ClassName' form: {path!r}"
        ) from error

    value: Any = import_module(module_name)
    for part in qualified_name.split("."):
        value = getattr(value, part)
    if not isinstance(value, type):
        raise TypeError(f"{path!r} does not resolve to a class")
    return value


def _next_geometry(
    modules: dict[str, dict[str, Any]],
    geometry_unit: str = "px",
    grid_columns: int = DEFAULT_GRID_COLUMNS,
) -> tuple[int, int, int, int]:
    """Choose a predictable, non-overlapping panel area when none was given."""
    if geometry_unit == "grid":
        bottom = max(
            (
                module["geometry"][1] + module["geometry"][3]
                for module in modules.values()
            ),
            default=0,
        )
        width = min(DEFAULT_GRID_GEOMETRY[2], grid_columns)
        return 0, bottom, width, DEFAULT_GRID_GEOMETRY[3]

    bottom = max(
        (module["geometry"][1] + module["geometry"][3] for module in modules.values()),
        default=-_DEFAULT_PANEL_GAP,
    )
    return 0, bottom + _DEFAULT_PANEL_GAP, _DEFAULT_PANEL_WIDTH, _DEFAULT_PANEL_HEIGHT


def _move_geometry(
    geometry: tuple[int, int, int, int], dx: int, dy: int
) -> tuple[int, int, int, int]:
    x, y, width, height = geometry
    return max(0, x + dx), max(0, y + dy), width, height


def _resize_geometry(
    geometry: tuple[int, int, int, int],
    dx: int,
    dy: int,
    *,
    min_width: int = _MIN_PANEL_WIDTH,
) -> tuple[int, int, int, int]:
    """Resize from the bottom-right while keeping the top-left fixed."""
    x, y, width, height = geometry
    min_width = min(width, min_width)
    min_height = min(height, _MIN_PANEL_HEIGHT)
    return (
        x,
        y,
        max(min_width, width + dx),
        max(min_height, height + dy),
    )


def _drag_geometry(
    module: dict[str, Any],
    drag: dict[str, Any],
    dx: int,
    dy: int,
    *,
    settings: _DeckSettings = _DeckSettings(),
) -> tuple[int, int, int, int]:
    """Calculate a panel drag without coupling move and resize arguments."""
    if settings.geometry_unit == "grid":
        cell_width, cell_height = drag["cell_size"]
        if drag["mode"] == "move":
            return move_grid_geometry(
                drag["geometry"],
                dx,
                dy,
                cell_width=cell_width,
                cell_height=cell_height,
                grid_columns=settings.grid_columns,
            )
        return resize_grid_geometry(
            drag["geometry"],
            dx,
            dy,
            cell_width=cell_width,
            cell_height=cell_height,
            grid_columns=settings.grid_columns,
        )
    if drag["mode"] == "move":
        return _move_geometry(drag["geometry"], dx, dy)
    return _resize_geometry(
        drag["geometry"],
        dx,
        dy,
        min_width=module["min_panel_width"],
    )


def run_ui_process(
    command_queue: Any,
    event_queue: Any,
    ready_event: Any,
    settings: _DeckSettings = _DeckSettings(),
    window_active: Any = None,
) -> None:
    """Host all widget panels in one CustomTkinter application window."""
    root = None
    usage_after_id: str | None = None
    usage_stopped = False

    def stop_process_usage() -> None:
        nonlocal usage_after_id, usage_stopped
        usage_stopped = True
        if root is not None and usage_after_id is not None:
            try:
                root.after_cancel(usage_after_id)
            except (tk.TclError, ValueError):
                # The window may already have been destroyed externally.
                pass
            usage_after_id = None

    modules: dict[str, dict[str, Any]] = {}
    layout_width = settings.window_width
    window_initialized = False
    active_widget_id: str | None = None
    deck_enabled = True
    try:
        import customtkinter as ctk

        from ._status_text import StatusText

        theme.apply(settings.theme_definition or theme.resolve(settings.theme))
        root = ctk.CTk(fg_color=theme.WINDOW_BG_COLOR)
        root.withdraw()
        apply_window_icon(root, default=True)
        root.title("CardTable")
        if window_active is not None:
            def update_focus() -> None:
                try:
                    if root.focus_displayof() is not None:
                        window_active.set()
                    else:
                        window_active.clear()
                except tk.TclError:
                    window_active.clear()

            def focus_changed(_event: Any) -> None:
                root.after_idle(update_focus)

            root.bind_all("<FocusIn>", focus_changed, add="+")
            root.bind_all("<FocusOut>", focus_changed, add="+")
        # root.resizable(width=True, height=False)

        status_bar = ctk.CTkFrame(
            root,
            height=_STATUS_BAR_HEIGHT,
            corner_radius=0,
            fg_color=theme.STATUS_BAR_BG_COLOR,
        )
        status_bar.place(relx=0, rely=1, relwidth=1, anchor="sw")
        status_bar.pack_propagate(False)
        status_message = StatusText(status_bar, height=_STATUS_BAR_HEIGHT)
        status_layout = StatusText(status_bar, height=_STATUS_BAR_HEIGHT)
        status_layout.pack(side="right", padx=(10, 24))
        status_usage = StatusText(status_bar, height=_STATUS_BAR_HEIGHT)
        status_usage.pack(side="right")
        status_message.pack(side="left", fill="x", expand=True, padx=10)
        _bind_input_guard(root, lambda: not deck_enabled)

        usage = ProcessUsage()

        def update_process_usage() -> None:
            nonlocal usage_after_id
            if usage_stopped:
                return
            usage_after_id = None
            status_usage.configure(text=f"{usage.sample()} |")
            usage_after_id = root.after(1000, update_process_usage)

        update_process_usage()

        def send(event_type: str, widget_id: str, **values: Any) -> None:
            module = modules.get(widget_id, {})
            values.setdefault("attachment_id", module.get("attachment_id"))
            event_queue.put({"type": event_type, "widget_id": widget_id, **values})

        def visible_modules() -> list[dict[str, Any]]:
            return [
                module
                for module in modules.values()
                if module["visible"] and "popup_window" not in module
            ]

        def pixel_geometry(module: dict[str, Any]) -> tuple[int, int, int, int]:
            if settings.geometry_unit == "px":
                return module["geometry"]
            return grid_to_pixels(
                module["geometry"],
                layout_width,
                settings.grid_columns,
                settings.grid_aspect,
            )

        def layout_module(module: dict[str, Any]) -> None:
            x, y, width, height = pixel_geometry(module)
            module["frame"].configure(
                width=max(1, width - 2 * _PANEL_PADDING),
                height=max(1, height - 2 * _PANEL_PADDING),
            )
            if module["visible"]:
                module["frame"].place(x=x + _PANEL_PADDING, y=y + _PANEL_PADDING)

        def layout_grid_modules() -> None:
            for module in modules.values():
                if settings.geometry_unit == "grid" and "popup_window" not in module:
                    layout_module(module)

        def required_window_height() -> int:
            return max(
                (
                    pixel_geometry(module)[1] + pixel_geometry(module)[3]
                    for module in visible_modules()
                ),
                default=1,
            )

        def required_window_width() -> int:
            return max(
                (pixel_geometry(module)[0] + pixel_geometry(module)[2]
                 for module in visible_modules()),
                default=1,
            )

        def occupied_grid_columns() -> int:
            return max(
                (module["geometry"][0] + module["geometry"][2]
                 for module in visible_modules()),
                default=0,
            )

        def update_status_bar() -> None:
            active = modules.get(active_widget_id)
            text = ""
            if active is not None and active["visible"]:
                title = active["name"] or "Untitled"
                text = f"{title}  {active['geometry']}   |   "
            layout_info = (
                f"{occupied_grid_columns()}/{settings.grid_columns} cols"
                if settings.geometry_unit == "grid"
                else "Pixels"
            )
            status_layout.configure(text=f"{text}{required_window_width()} px | {layout_info}")
            status_bar.lift()

        def activate_module(widget_id: str) -> None:
            nonlocal active_widget_id
            active_widget_id = widget_id
            update_status_bar()

        def fit_window_to_panels() -> None:
            nonlocal layout_width, window_initialized
            visible = visible_modules()
            if not visible:
                update_status_bar()
                window_initialized = False
                root.withdraw()
                return

            # Let the window manager own fullscreen geometry. Refitting during
            # its Configure events interrupts the native fullscreen transition.
            if root.attributes("-fullscreen"):
                update_status_bar()
                return

            if not window_initialized:
                layout_width = settings.window_width
                window_initialized = True
                layout_grid_modules()

            update_status_bar()
            required_height = required_window_height() + _STATUS_BAR_HEIGHT
            root.minsize(1, required_height)
            root.geometry(f"{required_window_width()}x{required_height}")

        def resize_grid_layout(event: Any) -> None:
            nonlocal layout_width
            if event.widget is not root or not visible_modules():
                return
            width = max(1, round(root._reverse_window_scaling(event.width)))
            height = round(root._reverse_window_scaling(event.height))
            width_changed = width != required_window_width()
            if width_changed and settings.geometry_unit == "grid":
                right_column = occupied_grid_columns()
                layout_width = max(1, round(width * settings.grid_columns / right_column))
                layout_grid_modules()
            if width_changed or height != required_window_height() + _STATUS_BAR_HEIGHT:
                fit_window_to_panels()

        def emit_geometry(widget_id: str) -> None:
            module = modules.get(widget_id)
            if module is None:
                return
            send("geometry", widget_id, geometry=module["geometry"])

        def schedule_geometry(widget_id: str) -> None:
            module = modules.get(widget_id)
            if module is None:
                return
            token = module.get("geometry_after_id")
            if token is not None:
                root.after_cancel(token)

            def emit_scheduled(current_id: str = widget_id) -> None:
                current = modules.get(current_id)
                if current is None:
                    return
                current["geometry_after_id"] = None
                emit_geometry(current_id)

            module["geometry_after_id"] = root.after(
                _GEOMETRY_EVENT_DELAY_MS, emit_scheduled
            )

        def flush_geometry(widget_id: str) -> None:
            module = modules.get(widget_id)
            if module is None:
                return
            token = module.get("geometry_after_id")
            if token is not None:
                root.after_cancel(token)
                module["geometry_after_id"] = None
            emit_geometry(widget_id)

        def apply_geometry(widget_id: str, geometry: tuple[int, int, int, int]) -> None:
            module = modules[widget_id]
            if geometry == module["geometry"]:
                return
            module["geometry"] = geometry
            layout_module(module)
            if widget_id == active_widget_id:
                update_status_bar()
            schedule_geometry(widget_id)

        def begin_drag(widget_id: str, mode: str, event: Any) -> str:
            module = modules[widget_id]
            activate_module(widget_id)
            # The compact title used for name=None is easy to leave, especially
            # when grid snapping moves it away from the pointer. Keep receiving
            # motion and release events on the pressed Canvas/Label until release.
            event.widget.grab_set()
            module["drag"] = {
                "mode": mode,
                "mouse": (event.x_root, event.y_root),
                "geometry": module["geometry"],
                "target": event.widget,
            }
            if settings.geometry_unit == "grid":
                module["drag"]["cell_size"] = grid_cell_size(
                    layout_width,
                    settings.grid_columns,
                    settings.grid_aspect,
                )
            module["frame"].lift()
            return "break"

        def drag_module(widget_id: str, event: Any) -> str:
            module = modules.get(widget_id)
            if module is None or module["drag"] is None:
                return "break"
            drag = module["drag"]
            dx = int(event.x_root - drag["mouse"][0])
            dy = int(event.y_root - drag["mouse"][1])
            geometry = _drag_geometry(module, drag, dx, dy, settings=settings)
            apply_geometry(widget_id, geometry)
            return "break"

        def release_drag(module: dict[str, Any]) -> None:
            drag = module["drag"]
            if drag is not None:
                module["drag"] = None
                target = drag["target"]
                if target.grab_current() is target:
                    target.grab_release()

        def clamp_drag_to_screen(widget_id: str) -> None:
            module = modules[widget_id]
            available_height = max(
                1,
                root._reverse_window_scaling(
                    root.winfo_screenheight() - root.winfo_rooty()
                )
                - _STATUS_BAR_HEIGHT,
            )
            if settings.geometry_unit == "grid":
                _, cell_height = grid_cell_size(
                    layout_width, settings.grid_columns, settings.grid_aspect
                )
                max_bottom = max(1, int(available_height / cell_height))
            else:
                max_bottom = int(available_height)
            x, y, width, height = module["geometry"]
            if module["drag"]["mode"] == "move":
                height = min(height, max_bottom)
                y = min(y, max_bottom - height)
            else:
                y = min(y, max_bottom - 1)
                height = min(height, max_bottom - y)
            apply_geometry(widget_id, (x, y, width, height))

        def end_drag(widget_id: str, event: Any) -> str:
            drag_module(widget_id, event)
            module = modules.get(widget_id)
            if module is not None and module["drag"] is not None:
                # Keep the bottom handle reachable, accounting for the window's
                # screen position. Clamp only once the gesture is committed.
                clamp_drag_to_screen(widget_id)
                release_drag(module)
                # Resize the window only after release; resizing during a Card
                # drag causes flickering.
                fit_window_to_panels()
                # Finish resizing and repainting before returning to the native
                # event loop, which can otherwise present the old backing image.
                root.update_idletasks()
                flush_geometry(widget_id)
            return "break"

        def bind_drag(
            target: Any, widget_id: str, mode: str, *, bind_frame: bool = False
        ) -> None:
            def bind(sequence: str, callback: Any) -> None:
                target.bind(sequence, callback)
                if bind_frame:
                    # CTkFrame.bind forwards only to its Canvas. Also cover the
                    # outer frame so the entire colored bar accepts a press.
                    tk.Misc.bind(target, sequence, callback, add="+")

            bind(
                "<ButtonPress-1>",
                lambda event, current_id=widget_id, current_mode=mode: begin_drag(
                    current_id, current_mode, event
                ),
            )
            bind(
                "<B1-Motion>",
                lambda event, current_id=widget_id: drag_module(current_id, event),
            )
            bind(
                "<ButtonRelease-1>",
                lambda event, current_id=widget_id: end_drag(current_id, event),
            )

        def show_module(widget_id: str) -> None:
            module = modules[widget_id]
            if "popup_window" in module:
                module["visible"] = True
                module["popup_window"].deiconify()
                module["popup_window"].lift()
                return
            window_was_hidden = not visible_modules()
            module_was_hidden = not module["visible"]
            if not module["visible"]:
                module["visible"] = True
                layout_module(module)
            if module_was_hidden:
                fit_window_to_panels()
            if window_was_hidden:
                root.deiconify()
                root.lift()
            if module_was_hidden:
                emit_geometry(widget_id)

        def hide_module(widget_id: str) -> None:
            module = modules[widget_id]
            if "popup_window" in module:
                module["visible"] = False
                module["popup_window"].withdraw()
                return
            release_drag(module)
            if module["visible"]:
                module["frame"].place_forget()
                module["visible"] = False
            fit_window_to_panels()

        def close_window() -> None:
            if not deck_enabled:
                return
            for module in modules.values():
                release_drag(module)
            root.withdraw()
            event_queue.put({"type": "close_requested"})

        def create_popup(command: dict[str, Any], options: dict[str, Any]) -> None:
            widget_id = command["widget_id"]
            geometry = options.pop("geometry")
            show_on_create = options.pop("show_on_create", True)
            close_enabled = options.pop("popup_close_enabled", True)
            auto_height = options.pop("popup_auto_height", False)
            min_content_width = options.pop("popup_min_content_width", None)
            has_default = "popup_default" in options
            default = options.pop("popup_default", None)
            if settings.geometry_unit == "grid":
                _, _, width, height = grid_to_pixels(
                    geometry,
                    settings.window_width,
                    settings.grid_columns,
                    settings.grid_aspect,
                )
            else:
                _, _, width, height = geometry
            window = ctk.CTkToplevel(root, fg_color=theme.CARD_BG_COLOR)
            window.withdraw()
            try:
                apply_window_icon(window)
                window.title(command["name"] or "")
                window.attributes("-topmost", True)
                # CTk geometry uses logical units; screen dimensions are physical.
                screen_width = window._reverse_window_scaling(
                    window.winfo_screenwidth()
                )
                screen_height = window._reverse_window_scaling(
                    window.winfo_screenheight()
                )
                x = max(0, round((screen_width - width) / 2))
                y = max(0, round((screen_height - height) / 2))
                window.geometry(f"{width}x{height}+{x}+{y}")

                def cancel(_event: Any = None) -> str:
                    if close_enabled:
                        hide_module(widget_id)
                        send("close_requested", widget_id)
                    return "break"

                window.protocol("WM_DELETE_WINDOW", cancel)
                body = ctk.CTkFrame(
                    window,
                    fg_color=theme.CARD_BG_COLOR,
                    border_width=1,
                    border_color=options.pop("border_color", theme.CARD_BORDER_COLOR),
                )
                body.pack(fill="both", expand=True)
                widget_type = _resolve_class(command["widget_class"])
                ui = widget_type._create_ui(
                    body,
                    emit=lambda payload: send(
                        "input",
                        widget_id,
                        payload=payload,
                        attachment_id=command.get("attachment_id"),
                    ),
                    **options,
                )
                if min_content_width is not None:
                    window.update_idletasks()
                    content_width = max(
                        (child.winfo_reqwidth() for child in ui._container.winfo_children()),
                        default=0,
                    )
                    width = max(
                        min_content_width,
                        round(ui._container._reverse_widget_scaling(content_width)) + 22,
                    )
                    x = max(0, round((screen_width - width) / 2))
                    window.geometry(f"{width}x{height}+{x}+{y}")
                if auto_height:
                    # The scrollable frame's requested height is its viewport,
                    # not its contents. Measure the inner frame after layout.
                    window.update_idletasks()
                    content_height = ui._container.winfo_reqheight()
                    height = min(
                        round(screen_height),
                        max(1, round(ui._container._reverse_widget_scaling(content_height)) + 2),
                    )
                    y = max(0, round((screen_height - height) / 2))
                    window.geometry(f"{width}x{height}+{x}+{y}")
                if has_default:
                    from .elements.button import _BtnPressed
                    from .elements.result_button import _ResultBtn

                    selected = next(
                        (
                            button for button in ui._button_definitions.values()
                            if isinstance(button, _ResultBtn)
                            and button.result is default
                        ),
                        None,
                    )

                    def accept(_event: Any = None) -> str:
                        if selected is not None and selected.state != "disabled":
                            send("input", widget_id, payload=_BtnPressed(selected.id))
                        return "break"

                    window.bind("<Return>", accept, add="+")
                    window.bind("<KP_Enter>", accept, add="+")
                    if selected is not None:
                        window.after_idle(ui._buttons[selected.id].focus_set)
                window.bind("<Escape>", cancel, add="+")
            except Exception:
                window.destroy()
                raise
            modules[widget_id] = {
                "attachment_id": command.get("attachment_id"),
                "frame": window,
                "popup_window": window,
                "ui": ui,
                "geometry": tuple(geometry),
                "geometry_after_id": None,
                "drag": None,
                "visible": False,
            }
            if show_on_create:
                show_module(widget_id)

        def create_module(command: dict[str, Any]) -> None:
            widget_id = command["widget_id"]
            options = dict(command.get("options", {}))
            if options.pop("popup", False):
                create_popup(command, options)
                return
            title_bg_color = options.pop("title_bg_color", theme.TITLE_BG_COLOR)
            title_font_color = options.pop("title_font_color", theme.TITLE_FONT_COLOR)
            border_color = options.pop("border_color", theme.CARD_BORDER_COLOR)
            geometry = options.pop("geometry", None) or _next_geometry(
                modules, settings.geometry_unit, settings.grid_columns
            )
            show_on_create = options.pop("show_on_create", True)
            if settings.geometry_unit == "grid":
                x, y, width, height = grid_to_pixels(
                    geometry,
                    layout_width,
                    settings.grid_columns,
                    settings.grid_aspect,
                )
            else:
                x, y, width, height = geometry

            # CustomTkinter requires width and height in the constructor rather
            # than in place().  Disabling propagation makes geometry the panel's
            # outer area, with two pixels of padding on every side.
            frame = ctk.CTkFrame(
                root,
                width=max(1, width - 2 * _PANEL_PADDING),
                height=max(1, height - 2 * _PANEL_PADDING),
                corner_radius=_PANEL_CORNER_RADIUS,
                bg_color=root.cget("fg_color"),
                fg_color=theme.CARD_BG_COLOR,
                border_width=1,
                border_color=border_color,
            )
            # Grid boundaries can produce odd pixel sizes.  CTk otherwise
            # floors the rounded border to even dimensions, leaving a gap.
            frame._draw_engine.set_round_to_even_numbers(False, False)
            frame._draw()
            frame.pack_propagate(False)

            if command["name"] is None:
                title = ctk.CTkFrame(
                    frame,
                    height=_UNTITLED_BAR_HEIGHT,
                    corner_radius=_PANEL_CONTENT_RADIUS,
                    fg_color=title_bg_color,
                )
            else:
                title = ctk.CTkLabel(
                    frame,
                    text=command["name"],
                    height=22,
                    anchor="w",
                    corner_radius=_PANEL_CONTENT_RADIUS,
                    fg_color=title_bg_color,
                    text_color=title_font_color,
                    font=ctk.CTkFont(size=11, weight="bold"),
                )
            title.configure(cursor="fleur")
            title._canvas.configure(cursor="fleur")
            title.pack(
                fill="x",
                padx=_PANEL_CORNER_RADIUS,
                pady=(4, 0),
            )

            body = ctk.CTkFrame(
                frame,
                corner_radius=_PANEL_CONTENT_RADIUS,
                fg_color=theme.CARD_BG_COLOR,
            )
            body.pack(
                fill="both",
                expand=True,
                padx=_PANEL_CORNER_RADIUS,
                pady=(0, _PANEL_CORNER_RADIUS),
            )

            bind_drag(title, widget_id, "move", bind_frame=command["name"] is None)

            # The panel itself has rounded corners.  Rebuild only the
            # bottom-right corner as a square so it remains a clear resize
            # affordance while the other three corners stay rounded.
            corner_patch = ctk.CTkFrame(
                frame,
                width=_PANEL_CORNER_SIZE,
                height=_PANEL_CORNER_SIZE,
                corner_radius=0,
                fg_color=theme.CARD_BG_COLOR,
            )
            corner_patch.place(relx=1.0, rely=1.0, anchor="se")
            corner_patch.lower(title)
            right_border = ctk.CTkFrame(
                frame,
                width=1,
                height=_PANEL_CORNER_SIZE,
                corner_radius=0,
                fg_color=border_color,
            )
            right_border.place(relx=1.0, rely=1.0, anchor="se")
            right_border.lower(title)
            bottom_border = ctk.CTkFrame(
                frame,
                width=_PANEL_CORNER_SIZE,
                height=1,
                corner_radius=0,
                fg_color=border_color,
            )
            bottom_border.place(relx=1.0, rely=1.0, anchor="se")
            bottom_border.lower(title)

            # Tk widgets have rectangular backgrounds even when CTk calls them
            # transparent.  Use narrow rows so only the handle triangle covers
            # the content beneath the handle.
            resize_handle = []
            for row in range(_PANEL_CORNER_SIZE):
                strip = ctk.CTkFrame(
                    frame,
                    width=row + 1,
                    height=1,
                    corner_radius=0,
                    bg_color=theme.RESIZE_HANDLE_COLOR,
                    fg_color=theme.RESIZE_HANDLE_COLOR,
                    cursor="bottom_right_corner",
                )
                strip.place(
                    relx=1.0,
                    rely=1.0,
                    y=row + 1 - _PANEL_CORNER_SIZE,
                    anchor="se",
                )
                bind_drag(strip, widget_id, "resize")
                resize_handle.append(strip)

            try:
                widget_type = _resolve_class(command["widget_class"])
                ui = widget_type._create_ui(
                    body,
                    emit=lambda payload, current_id=widget_id: send(
                        "input",
                        current_id,
                        payload=payload,
                        attachment_id=command.get("attachment_id"),
                    ),
                    **options,
                )
                _bind_panel_activation(
                    frame, lambda current_id=widget_id: activate_module(current_id)
                )
                _bind_input_guard(frame, lambda: not deck_enabled)
            except Exception:
                frame.destroy()
                raise

            modules[widget_id] = {
                "attachment_id": command.get("attachment_id"),
                "name": command["name"],
                "frame": frame,
                "ui": ui,
                "corner_parts": (corner_patch, right_border, bottom_border),
                "resize_handle": resize_handle,
                "geometry": tuple(geometry),
                "min_panel_width": _MIN_PANEL_WIDTH,
                "geometry_after_id": None,
                "drag": None,
                "visible": False,
            }

            if show_on_create:
                show_module(widget_id)
            else:
                emit_geometry(widget_id)

        def handle(command: dict[str, Any]) -> bool:
            nonlocal deck_enabled
            command_type = command.get("type")
            widget_id = command.get("widget_id", "")
            try:
                if command_type == "create":
                    create_module(command)
                    send("ready", widget_id)
                elif command_type == "status_text":
                    status_message.configure(text=command["text"])
                elif command_type == "deck_enabled":
                    deck_enabled = command["enabled"]
                    if not deck_enabled:
                        for module in modules.values():
                            if "popup_window" not in module:
                                release_drag(module)
                                _bind_input_guard(
                                    module["frame"], lambda: not deck_enabled
                                )
                elif command_type == "update":
                    reveal = modules[widget_id]["ui"]._update_ui(command.get("payload"))
                    module = modules[widget_id]
                    if not deck_enabled and "popup_window" not in module:
                        _bind_input_guard(module["frame"], lambda: not deck_enabled)
                    if reveal is not False:
                        show_module(widget_id)
                    if command.get("ack"):
                        send("update_done", widget_id)
                elif command_type == "button_update":
                    modules[widget_id]["ui"]._update_button(
                        command.get("button_id"),
                        state=command.get("state"),
                        label=command.get("label"),
                    )
                elif command_type == "button_finished":
                    modules[widget_id]["ui"]._finish_button_ui(command.get("button_id"))
                elif command_type == "element_update":
                    modules[widget_id]["ui"]._update_element(
                        command.get("element_id"),
                        state=command.get("state"),
                        label=command.get("label"),
                    )
                elif command_type == "show":
                    show_module(widget_id)
                elif command_type == "hide":
                    hide_module(widget_id)
                elif command_type == "destroy":
                    module = modules.pop(widget_id, None)
                    if module is not None:
                        release_drag(module)
                        token = module.get("geometry_after_id")
                        if token is not None:
                            root.after_cancel(token)
                        module["frame"].destroy()
                        fit_window_to_panels()
                elif command_type == "shutdown":
                    return False
            except Exception as error:
                _logger.exception(
                    "UI command %s failed for widget %s", command_type, widget_id
                )
                send(
                    "error",
                    widget_id,
                    message=f"{type(error).__name__}: {error}",
                    attachment_id=command.get("attachment_id"),
                )
            return True

        def drain_commands() -> None:
            keep_running = True
            for _ in range(100):
                try:
                    command = command_queue.get_nowait()
                except Empty:
                    break
                keep_running = handle(command)
                if not keep_running:
                    break

            if keep_running:
                root.after(10, drain_commands)
            else:
                stop_process_usage()
                root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_window)
        root.bind("<Configure>", resize_grid_layout, add="+")
        ready_event.set()
        root.after(0, drain_commands)
        root.mainloop()
    except Exception as error:
        _logger.exception("UI process failed")
        event_queue.put(
            {
                "type": "host_error",
                "message": f"{type(error).__name__}: {error}",
            }
        )
        ready_event.set()
    finally:
        stop_process_usage()
        for module in tuple(modules.values()):
            try:
                module["frame"].destroy()
            except Exception:
                pass
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass
