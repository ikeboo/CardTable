"""USBCamera monitoring sample: python examples/sample_app.py."""

import cardtable as c


class MyApp(c.Dealer):
    def setup(self):
        c.set_logger("./logs")  # optional, if you want to save log
        # Event Trigger
        self.trigger = c.KeyTrigger("<ctrl>+k", self.capture)
        self.scheduler = c.ScheduleTrigger("* * * * *", self.show_timestamp)
        self.prev_timer = c.TimerTrigger(100, self.update_preview)
        self.text_timer = c.TimerTrigger(500, self.update_text)
        # Service
        self.camera = c.Camera(0)
        # Create UI
        with c.Card(0, 0, 3, 7, "Controls") as self.val_card:
            self.file_drop = c.FileDrop("Drop or click to select", "File Select")
            self.mode = c.Radio(["A", "B", "C"], "Mode")
            self.input = c.Entry("Input here")
            self.switch = c.Switch(label="Monitor")
            c.Separator("Test")
            self.value = c.Slider(0, 100, 1, "Value")
            self.combo = c.ComboBox(["A", "B", "C"], "Menu")
            with c.Row():
                self.led_red = c.LED("red", "LED")
                self.led_green = c.LED("limegreen", "Cap.")
            with c.Row():
                c.Button("Capture", self.capture)
                c.Button("Message", self.show_message)
                c.Button("Geometry", self.show_geometry)

        with c.Card(3, 0, 3, 7, "Camera"):
            self.preview = c.Image("Monitor")
            self.captured = c.Image("Captured")

        with c.Card(6, 5, 6, 2, "Texts"):
            with c.Row():
                self.val_text = c.Text(4)
                self.geo_text = c.Text(4)

        with c.Card(9, 0, 3, 5, None):
            self.table = c.Table(["mark", "value"], 8, [1, 4])
            self.label = c.Label(
                "State",
                anchor="center",
                bg_color="gray",
                corner_radius=10,
                font_scale=1.5,
            )

        with c.Card(6, 0, 3, 5, "Visualize"):
            self.gauge = c.Gauge(
                (0, 50, 100, 200, 255),
                unit="",
                colors=["gray", "palegreen", "gold", "red"],
            )
            self.plot = c.SignalPlot("Waveform", aspect=(4, 1.5), follow_window=200)

    # callbacks
    def capture(self):
        self.captured.set(self.camera.get())
        self.led_red.flash(50)

    def show_message(self):
        c.Deck.print("Start")
        c.show_message("Hello", auto_close_sec=3)
        c.Deck.print("Done")

    def update_preview(self, event: c.TriggerEvent):
        img = self.camera.execute()
        mean = img.mean()
        self.preview.set(img)
        self.led_green.set(not self.led_green.get())
        self.gauge.set(mean)
        self.plot.append(mean)
        self.table.append(
            ["⬛︎", mean],
            text_colors=["red" if mean > 120 else "palegreen", None],
        )
        self.label.set(
            "NG" if mean > 120 else "OK",
            bg_color="red" if mean > 120 else "palegreen",
        )

    def update_text(self, event: c.TriggerEvent):
        self.val_text.append(f"Time:{event.timestamp:.1f}\n")

    def show_geometry(self):
        self.geo_text.set({card.name: card.geometry for card in c.Deck.get_cards()})

    def show_timestamp(self, event: c.TriggerEvent):
        c.Deck.print("ScheduleTrigger is triggered at ", event.data["scheduled_at"])


if __name__ == "__main__":
    MyApp().start()
