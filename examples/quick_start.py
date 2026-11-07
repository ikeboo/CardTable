"""Quick start to capture image"""

import cardtable as c


class MyApp(c.Dealer):
    def setup(self):
        with c.Card(0, 0, 4, 3, "Hello cardtable"):
            self.message = c.Entry("Enter a message")
            self.output = c.Text()
            with c.Row():
                c.Button("Show", self.show)
                c.Button("Clear", self.clear)

    def show(self):
        self.output.set(self.message.get())

    def clear(self):
        self.message.reset()
        self.output.reset()


if __name__ == "__main__":
    MyApp().start()
