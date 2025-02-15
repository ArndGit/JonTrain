from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.core.window import Window
from kivy.clock import Clock
from kivy.utils import get_color_from_hex
from datetime import datetime
from random import randint
import os
import json
import webbrowser

__version__ = "0.7"
HIGHSCORE_FILE = "highscores.json"

#if platform == "android":
#    from jnius import autoclass
#    PythonActivity = autoclass('org.kivy.android.PythonActivity')
#    Context = autoclass('android.content.Context')
#    Vibrator = PythonActivity.mActivity.getSystemService(Context.VIBRATOR_SERVICE)


CATEGORIES = {
    "Mal-nehmen": "mult",
    "Teilen": "div",
    "Mal-nehmen und Teilen ohne Rest": "mult_div",
    "Teilen mit Rest": "div_rest",
    "Teilen mit und ohne Rest": "div_divrest",
    "Alles gemischt": "all"
}


def convert_to_number(value):
    return int(value) if value.strip() else 0

def scale_font(base_size):
    """Scales font size based on screen width for better readability."""
    screen_width, _ = Window.size
    scale_factor = screen_width / 600  # Reference width for scaling
    return int(base_size * scale_factor)

def vibrate(times=1):
    """Vibriert das Gerät entsprechend der Anzahl der Impulse."""
#    if platform == "android":
#        for _ in range(times):
#            Vibrator.vibrate(200)
#            Clock.schedule_once(lambda dt: None, 0.2)


class MathTrainer(App):
    def build(self):
        self.result_reset_timer = None
        self.category = None
        self.points = 0
        self.question = None
        self.time_left = 300
        self.current_question = None
        self.previous_question = ""
        self.answer = {"tens": "", "ones": "", "remainder": ""}
        self.button_refs = {"tens": None, "ones": None, "remainder": None}
        self.load_highscores()
        self.main_menu()
        return self.layout

    def show_about(self, instance=None):
        """Displays an 'Über' screen with app info and a back button."""
        self.layout.clear_widgets()

        self.layout.add_widget(Label(text="Über JonTrain", font_size=scale_font(28)))
        self.layout.add_widget(Label(text="Autor: Arnd", font_size=scale_font(24)))
        self.layout.add_widget(Label(text="Tester: Jona, Vincent, Ben", font_size=scale_font(24)))
        self.layout.add_widget(Label(text=f"Version: {__version__}", font_size=scale_font(24)))

        license_btn = Button(text="Lizenz", font_size=scale_font(24), on_press=self.show_license)
        self.layout.add_widget(license_btn)

        support_btn = Button(text="Unterstütze meinen Verein", font_size=scale_font(24), on_press=self.open_support_link)
        self.layout.add_widget(support_btn)

        back_btn = Button(text="Zurück", font_size=24, on_press=self.return_to_main_menu)
        self.layout.add_widget(back_btn)

    def open_support_link(self, instance):
        """Öffnet den PayPal-Spendenlink im Standard-Browser."""
        url = "https://www.paypal.com/donate/?hosted_button_id=PND6Y8CGNZVW6"
        webbrowser.open(url)


    def load_highscores(self):
        if os.path.exists(HIGHSCORE_FILE):
            with open(HIGHSCORE_FILE, "r") as file:
                self.highscores = json.load(file)
        else:
            self.highscores = {cat: [] for cat in CATEGORIES.values()}

    def clear_input(self):
        """Clears input and resets button selections"""
        for key in self.button_refs:
            if self.button_refs[key]:
                self.button_refs[key].background_color = (1, 1, 1, 1)  # Reset button color
        self.answer = {"tens": "", "ones": "", "remainder": ""}
        self.button_refs = {"tens": None, "ones": None, "remainder": None}
        self.update_answer_display()

    def save_highscore(self, instance):
        """Saves the highscore with date & time, then shows the leaderboard if player made it."""
        player_name = str(self.name_input.text).strip() if str(self.name_input.text).strip() else "Anonym"
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")  #  Format: DD.MM.YYYY HH:MM

        if self.category not in self.highscores:
            self.highscores[self.category] = []

        new_entry = {
            "name": player_name,
            "points": self.points,
            "date": timestamp
        }

        self.highscores[self.category].append(new_entry)

        #  Sort & limit to top 10
        self.highscores[self.category] = sorted(self.highscores[self.category], key=lambda x: x["points"], reverse=True)[:10]

        with open(HIGHSCORE_FILE, "w") as file:
            json.dump(self.highscores, file, indent=4)

        #  Check if player made it into the top 10, then show highscore
        if new_entry in self.highscores[self.category]:
            self.show_highscore(self.category, new_entry)
        else:
            self.main_menu()  # If not in top 10, return to main menu

    def main_menu(self):
        self.layout = BoxLayout(orientation="vertical")

        title = Label(text="JonTrain Rechentrainer", font_size=scale_font(32))
        self.layout.add_widget(title)

        for cat_name, cat_key in CATEGORIES.items():
            row = BoxLayout()
            btn = Button(text=cat_name, font_size=scale_font(24), on_press=lambda x, key=cat_key: self.start_training(key))
            highscore_btn = Button(text="H", font_size=scale_font(24), on_press=lambda x, key=cat_key: self.show_highscore(key), size_hint_x=0.3)
            row.add_widget(btn)
            row.add_widget(highscore_btn)
            self.layout.add_widget(row)

        about_btn = Button(text="Über", font_size=scale_font(24), on_press=self.show_about)
        self.layout.add_widget(about_btn)

    def show_highscore(self, category, new_entry=None):
        """Displays the highscore list with rank, name, time, and date. Highlights new entry if applicable."""
        self.layout.clear_widgets()
        self.layout.add_widget(Label(text=f"Rangliste für {next(key for key, value in CATEGORIES.items() if value == category)}", font_size=scale_font(28)))

        scores = self.highscores.get(category, [])
        
        if scores:
            for rank, score in enumerate(scores, start=1):
                highlight = "[b]" if score == new_entry else ""  #  Highlight new score
                reset = "[/b]" if score == new_entry else ""
                self.layout.add_widget(Label(
                    text=f"{highlight}#{rank} {score['name']} - {score['points']} Punkte ({score['date']}){reset}",
                    font_size=scale_font(24),
                    markup=True  #  Allows bold formatting
                ))
        else:
            self.layout.add_widget(Label(text="Keine Einträge vorhanden", font_size=scale_font(24)))

        back_btn = Button(text="Zurück", font_size=scale_font(24), on_press=self.return_to_main_menu)
        self.layout.add_widget(back_btn)

    def return_to_main_menu(self, instance=None):
        """Fix for returning to the main menu properly."""
        Clock.unschedule(self.update_timer)
        self.layout.clear_widgets()  #  Ensure the UI is fully reset
        self.main_menu()  #  Rebuild the main menu properly
        self.root.clear_widgets()  #  Fix for blank screen issue
        self.root.add_widget(self.layout)  #  Ensure layout is reattached to the screen

    def start_training(self, category):
        self.category = category
        self.points = 0
        self.time_left = 300
        self.layout.clear_widgets()

        top_bar = BoxLayout()

        left_spacer = Label(size_hint_x=0.15)
        self.prev_question_label = Label(text="", font_size=scale_font(24), halign="left")
        exit_btn = Button(text="X", font_size=scale_font(16), size_hint_x=0.15, on_press=self.return_to_main_menu)
        
        top_bar.add_widget(left_spacer)
        top_bar.add_widget(self.prev_question_label )
        top_bar.add_widget(exit_btn)
        self.layout.add_widget(top_bar)

        separator = Label(text="―" * 50, font_size=scale_font(16), size_hint_y=None, height=scale_font(8))
        self.layout.add_widget(separator)
        
  
        self.question = None 
        self.question_label = Label(text="", font_size=scale_font(28))
        self.layout.add_widget(self.question_label)

        self.answer_label = Label(text="", font_size=scale_font(28))
        self.layout.add_widget(self.answer_label)
        
        separator2 = Label(text="―" * 50, font_size=scale_font(16), size_hint_y=None, height=scale_font(8))
        self.layout.add_widget(separator2)
        

        self.button_refs = {"tens": None, "ones": None, "remainder": None}

        num_buttons = [
            [("10", "tens"), ("20", "tens"), ("30", "tens"), ("40", "tens"), ("50", "tens"),
             ("60", "tens"), ("70", "tens"), ("80", "tens"), ("90", "tens"), ("100", "tens")],
            [("1", "ones"), ("2", "ones"), ("3", "ones"), ("4", "ones"),
             ("5", "ones"), ("6", "ones"), ("7", "ones"), ("8", "ones"), ("9", "ones"), ("10", "tens")],
            [("R0", "remainder"), ("R1", "remainder"), ("R2", "remainder"), ("R3", "remainder"),
             ("R4", "remainder"), ("R5", "remainder"), ("R6", "remainder"), ("R7", "remainder"),
             ("R8", "remainder"), ("R9", "remainder")]
        ]

        for row in num_buttons:
            button_row = BoxLayout()
            for num, group in row:
                btn = Button(text=num, font_size=scale_font(24), on_press=lambda x, grp=group: self.toggle_input(x, grp))
                button_row.add_widget(btn)
            self.layout.add_widget(button_row)

        control_row = BoxLayout()
        submit_btn = Button(text="EINGABE", font_size=scale_font(24), on_press=self.check_answer)
        clear_btn = Button(text="LÖSCHEN", font_size=scale_font(24), on_press=lambda x: self.clear_input())
        control_row.add_widget(clear_btn)
        control_row.add_widget(submit_btn)
        self.layout.add_widget(control_row)

        self.timer_label = Label(text=f"Zeit: {self.time_left} s", font_size=scale_font(24))
        self.layout.add_widget(self.timer_label)

        self.points_label = Label(text=f"Punkte: {self.points}", font_size=scale_font(24))
        self.layout.add_widget(self.points_label)

        Clock.schedule_interval(self.update_timer, 1)
        self.generate_question()

    def generate_question(self):
        """Picks a random case (1-10) and retries until a valid question is generated."""
        while True:  #  Keep retrying until a valid question is found
            case = randint(1, 10)  #  Pick a random case 1-10

            if case < 5 and self.category in ["mult", "mult_div", "all"]:
                a, b = randint(1, 10), randint(1, 10)
                self.current_question = (a, b, "mult")
                self.question = f"{a} × {b}"
                self.question_label.text = f"Was ist {a} × {b}?"
                break  #  Valid, exit loop

            elif case < 8 and self.category in ["div", "mult_div", "div_divrest", "all"]:
                a, b = randint(1, 10), randint(1, 10)
                self.current_question = (a * b, b, "div")
                self.question = f"{a * b} ÷ {b}"
                self.question_label.text = f"Was ist {a * b} ÷ {b}?"
                break  #  Valid, exit loop

            elif case >= 8 and self.category in ["div_rest", "div_divrest", "all"]:
                a, b = randint(1, 10), randint(2, 10)
                remainder = randint(0, b - 1)
                self.current_question = (a * b + remainder, b, remainder, "div_rest")
                self.question = f"{a * b + remainder} ÷ {b}"
                self.question_label.text = f"Was ist {a * b + remainder} ÷ {b}?"
                break  #  Valid, exit loop

    def toggle_input(self, instance, group):
        """Ensures only one button per category is selected at a time"""
        if self.button_refs[group]:  
            self.button_refs[group].background_color = (1, 1, 1, 1)  # Reset old button

        if self.button_refs[group] == instance:  
            self.answer[group] = ""  
            self.button_refs[group] = None  
        else:
            self.answer[group] = instance.text  
            self.button_refs[group] = instance  
            instance.background_color = (0.5, 1, 0.5, 1)  # Highlight selected

        self.update_answer_display()

    def update_answer_display(self):
        """Updates input display field"""
        tens = convert_to_number(self.answer["tens"] if self.answer["tens"] else "")
        ones = convert_to_number(self.answer["ones"] if self.answer["ones"] else "")
        remainder = self.answer["remainder"] if self.answer["remainder"] else ""
        self.answer_label.text = f"{tens+ones}{remainder}"

    def check_answer(self, instance):
        """Checks if the given answer is correct and updates the score."""
        tens = convert_to_number(self.answer["tens"])
        ones = convert_to_number(self.answer["ones"])
        remainder = convert_to_number(self.answer["remainder"].replace("R", "")) if self.answer["remainder"] else 0
        user_answer = (tens + ones, remainder)

        correct_answer = None
        points_awarded = 0

        if self.current_question[-1] == "mult":
            correct_answer = (self.current_question[0] * self.current_question[1], 0)
            points_awarded = 1 if user_answer == correct_answer else -5

        elif self.current_question[-1] == "div":
            correct_answer = (self.current_question[0] // self.current_question[1], 0)
            points_awarded = 2 if user_answer == correct_answer else -3

        elif self.current_question[-1] == "div_rest":
            correct_answer = (self.current_question[0] // self.current_question[1], self.current_question[2])
            points_awarded = 5 if user_answer == correct_answer else -3

        if user_answer == correct_answer:
            result_text = f"{user_answer[0]}" + (f" R{user_answer[1]}" if user_answer[1] else "") +f" ist RICHTIG!"
            self.points += points_awarded
            vibrate(1)  #  1x vibrieren für richtig
            self.highlight_result((0, 1, 0, 1))  #  Grün für richtig
        else:
            correct_text = f"{correct_answer[0]}" + (f" R{correct_answer[1]}" if correct_answer[1] else "")
            result_text = f"{user_answer[0]}" + (f" R{user_answer[1]}" if user_answer[1] else "") + f" ist FALSCH!\n>>> {self.question} = {correct_text} <<<"
            self.points = max(0, self.points + points_awarded)
            vibrate(2)  #  2x vibrieren für falsch
            self.highlight_result((1, 0, 0, 1))  #  Rot für falsch
        self.prev_question_label.text = f"{result_text}"

        self.points_label.text = f"Punkte: {self.points}"

        self.generate_question()
        self.clear_input()

    def highlight_result(self, color):
        """Lässt die Ergebniszeile kurz aufleuchten."""
        self.prev_question_label.color = color
        
        #if self.result_reset_timer:
        #    Clock.unschedule(self.result_reset_timer)

        #Clock.schedule_once(partial(self.reset_result_color), 1)  #  Zurücksetzen nach 2s

    def reset_result_color(self, dt):
        """Setzt die Ergebniszeilenfarbe auf Weiß zurück."""
        self.prev_question_label.color = (1, 1, 1, 1)
        self.result_reset_timer = None 
        
    def update_timer(self, dt):
        """Updates countdown timer and handles end of game scenario."""
        if self.time_left > 0:
            self.time_left -= 1
            self.timer_label.text = f"Zeit: {self.time_left} s"
        else:
            Clock.unschedule(self.update_timer)
            self.end_game()

    def end_game(self):
        """Handles the end of the game by asking for the player's name and saving the highscore."""
        self.layout.clear_widgets()

        self.layout.add_widget(Label(text=f"Zeit abgelaufen! Deine Punkte: {self.points}", font_size=scale_font(28)))

        self.name_input = TextInput(hint_text="Dein Name", font_size=scale_font(24), multiline=False)
        self.layout.add_widget(self.name_input)

        submit_btn = Button(text="Speichern", font_size=scale_font(24), on_press=self.save_highscore)
        self.layout.add_widget(submit_btn)

  
    def save_highscore(self, instance):
        """Saves the highscore with date & time, then shows the leaderboard if player made it."""
        player_name = str(self.name_input.text).strip() if str(self.name_input.text).strip() else "Anonym"
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")  #  Format: DD.MM.YYYY HH:MM

        if self.category not in self.highscores:
            self.highscores[self.category] = []

        new_entry = {
            "name": player_name,
            "points": self.points,
            "date": timestamp  #  Store date & time properly
        }

        self.highscores[self.category].append(new_entry)

        #  Sort & limit to top 10
        self.highscores[self.category] = sorted(self.highscores[self.category], key=lambda x: x["points"], reverse=True)[:10]

        with open(HIGHSCORE_FILE, "w") as file:
            json.dump(self.highscores, file, indent=4)  #  JSON now stores date & time

        #  Show highscore if player made it into the top 10
        if new_entry in self.highscores[self.category]:
            self.show_highscore(self.category, new_entry)
        else:
            self.main_menu()  # If not in top 10, return to main menu


    def show_license(self, instance):
        self.layout.clear_widgets()
        self.layout.add_widget(Label(text="Lizenz (Deutsche Freie Software Lizenz)", font_size=scale_font(28)))

        license_text = """\
    DEUTSCHE FREIE SOFTWARE LIZENZ (DFSL)

    Präambel:
    Diese Lizenz erlaubt es Ihnen, die Software frei zu nutzen, zu studieren, zu verändern und weiterzugeben, solange die Freiheit der Software erhalten bleibt.

    1. Nutzungsrecht:
    - Jeder darf die Software für beliebige Zwecke verwenden, ohne Einschränkung.

    2. Verbreitung:
    - Die Software darf in unveränderter oder modifizierter Form weitergegeben werden.
    - Der Lizenztext muss mitgeliefert werden.
    - Änderungen müssen gekennzeichnet und unter derselben Lizenz veröffentlicht werden.

    3. Gewährleistungsausschluss:
    - Diese Software wird ohne Garantie bereitgestellt.
    - Der Autor übernimmt keine Haftung für Schäden, die durch die Nutzung der Software entstehen.

    4. Freiheitserhalt:
    - Diese Lizenz darf nicht durch andere Lizenzen ersetzt werden, die die Freiheit der Software einschränken.

    Weitere Details finden Sie unter https://dfsl.de
    """

        # ScrollView für den langen Lizenztext
        scroll = ScrollView(size_hint=(1, 0.85))  # 85% der Höhe für den Text
        license_label = Label(text=license_text, font_size=scale_font(16), 
                            halign="left", valign="top", text_size=(Window.width - 40, None), 
                            size_hint_y=None)

        # Automatische Anpassung der Höhe des Labels
        license_label.bind(texture_size=lambda instance, value: setattr(instance, 'height', value[1]))
        scroll.add_widget(license_label)

        # Zurück-Button
        back_btn = Button(text="Zurück", font_size=scale_font(24), size_hint=(1, 0.15), on_press=self.show_about)

        # Lizenz-Text in ScrollView + Zurück-Button in die Hauptansicht einfügen
        self.layout.add_widget(scroll)
        self.layout.add_widget(back_btn)



if __name__ == '__main__':
    MathTrainer().run()
