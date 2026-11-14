STYLE = """
QMainWindow, QWidget#studio { background:#f7f8fa; color:#222831; }
QWidget { font-family:'Noto Sans',sans-serif; font-size:13px; color:#303640; }
QFrame#sidebar { background:#ffffff; border-right:1px solid #e8ebf0; }
QFrame#inspector { background:#ffffff; border:1px solid #edf0f4; border-radius:16px; }
QFrame#metric { background:transparent; border:0; border-top:1px solid #e9edf3; border-radius:0; }
QLabel { background:transparent; }
QLabel#brand { font-size:21px; font-weight:800; letter-spacing:-.5px; color:#20252d; }
QLabel#heading { font-size:30px; font-weight:700; letter-spacing:-1px; color:#1d2635; }
QLabel#panelHeading { font-size:17px; font-weight:700; color:#202731; }
QLabel#section { color:#505b6c; font-size:13px; font-weight:500; }
QLabel#muted { color:#596579; font-size:13px; }
QLabel#metricValue { font-family:'Lato','Inter',sans-serif; font-size:30px; font-weight:700; color:#202731; }
QLabel#chip { background:#eef1f5; border:1px solid #eef1f5; border-radius:14px; padding:5px 10px; color:#536074; font-size:13px; }
QLabel#chip[online="true"] { color:#325bb4; background:#eaf0ff; border-color:#c9d8fb; }
QLabel#status { color:#53657e; font-size:13px; }
QLabel#canvasCaption { color:#7b8797; font-family:'DejaVu Sans Mono',monospace; font-size:10px; letter-spacing:1px; }
QPushButton { background:#f4f6f9; border:1px solid #e8ebf0; border-radius:7px; padding:9px 12px; font-weight:600; }
QPushButton:hover { background:#e9edf3; border-color:#9aaec9; }
QPushButton:pressed { background:#e5edfc; }
QPushButton:focus { border:2px solid #3569e8; }
QPushButton:disabled { color:#969eaa; background:#edeff2; border-color:#e0e4ea; }
QPushButton#primary { background:#202938; color:#ffffff; border:1px solid #202938; border-radius:9px; padding:12px 23px; font-weight:800; }
QPushButton#primary:hover { background:#344056; border-color:#344056; }
QPushButton#primary:disabled { background:#e8ebf0; border-color:#e8ebf0; color:#98a1b1; }
QPushButton#nav { text-align:left; background:transparent; color:#707a87; border:0; border-left:2px solid transparent; border-radius:7px; padding:12px 14px; font-size:14px; font-weight:600; }
QPushButton#nav:hover { background:#f4f6f9; color:#283850; }
QPushButton#nav:checked { background:#edf0fb; border-left:2px solid transparent; color:#293955; }
QPushButton#nav:focus, QPushButton#segment:focus, QPushButton#primary:focus { border:2px solid #3569e8; }
QPushButton#segment { background:transparent; border:1px solid transparent; padding:7px 11px; color:#788493; font-size:12px; }
QPushButton#segment:hover { color:#2f63cf; }
QPushButton#segment:checked { background:#ffffff; border:1px solid #d5dfef; color:#263b63; border-radius:6px; }
QComboBox, QLineEdit, QSpinBox { background:#f4f6f9; border:1px solid #e3e7ee; border-radius:6px; padding:7px 9px; min-height:21px; selection-background-color:#d9e6ff; }
QComboBox:focus, QLineEdit:focus, QSpinBox:focus { border-color:#4b7be8; background:#ffffff; }
QComboBox::drop-down { border:0; width:20px; }
QComboBox QAbstractItemView { background:#ffffff; border:1px solid #d0d9e6; selection-background-color:#e4edff; }
QScrollArea { background:transparent; border:0; }
QScrollArea > QWidget > QWidget { background:transparent; }
QScrollBar:vertical { background:transparent; width:6px; margin:2px; }
QScrollBar::handle:vertical { background:#c9ced6; min-height:30px; border-radius:3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QProgressBar { border:0; background:#e0e5ed; border-radius:2px; height:3px; }
QProgressBar::chunk { background:#557ee0; border-radius:2px; }
QToolTip { background:#ffffff; color:#303b4a; border:1px solid #ccd6e5; padding:5px; }
"""
