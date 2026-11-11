"""
Smart MemoPad - 수식 계산이 가능한 스마트 메모장 (PySide6)

주요 기능:
    - 메모(주기능): 자동 저장(2초), 이전 세션 백업(.bak), F4 지우기(Ctrl+Z 실행 취소 지원)
    - 수식 계산(보조):
      · 상단 수식 입력 후 Enter 또는 '=' 클릭 → 메모 끝에 "수식 = 10진수 ( 0x16진수 )" 자동 추가
      · 메모장 내 인라인 계산 (Ctrl+Enter / F5): 현재 줄 또는 선택한 수식을 즉시 계산하여 그 자리에 결과 삽입
      · 정수는 무한 정밀도로 정확하게 계산 (64비트 이상 16진수 연산 완벽 지원)
      · 16진수(0x/0X), 2진수(0b/0B), 음수 부호(-5, 2*-3), 괄호, 거듭제곱(^) 지원
      · 실수(float) 결과는 순수 10진수로 깔끔하게 표시 (불필요한 0x0 생략)
      · 연산자 우선순위: ^(거듭제곱, 우결합) > 부호(+ -) > * / % > + -
      · eval() 없는 안전한 자체 재귀 하강 파서(Recursive Descent Parser) 탑재
    - 편리한 편의 기능:
      · 상단 입력창 수식 히스토리: ↑ / ↓ 방향키로 이전 입력 수식 탐색
      · 테마 전환 (F6): 다크 모드 / 라이트 모드 전환 (설정 자동 저장)
      · 글꼴 크기 조절 (Ctrl+↑ / Ctrl+↓): 기존 작성된 메모 전체에 즉시 크기 반영 및 보존
      · 항상 위에 표시 (Ctrl+T): 작업 창 위에 고정
"""

import math
import os
import shutil
import sys
from datetime import datetime
from typing import List, Tuple, Union

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QIcon, QKeyEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget
)


def get_app_path() -> str:
    """PyInstaller EXE 또는 일반 스크립트 실행 시 실제 파일이 위치한 폴더 반환"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


# 리소스(아이콘 등) 경로 (PyInstaller _MEIPASS 지원)
BASE_DIR = getattr(sys, '_MEIPASS', get_app_path())
ICON_PATH = os.path.join(BASE_DIR, "icon.ico")
if not os.path.exists(ICON_PATH):
    ICON_PATH = os.path.join(get_app_path(), "icon.ico")


###############################################################################################
# 안전한 수식 파서 & 계산기 (No eval)
###############################################################################################
Number = Union[int, float]

MAX_POW_EXPONENT = 100000   # 정수 거듭제곱 지수 상한 (과도한 연산 방지)
MAX_RESULT_BITS = 4096      # 결과 정수 크기 상한 (약 1233자리)


class CalcError(Exception):
    """사용자에게 보여줄 수식 계산 오류"""
    pass


class MathCalculator:
    """수식 계산 (재귀 하강 파서).

    문법:
        expr    := term (('+' | '-') term)*
        term    := unary (('*' | '/' | '%') unary)*
        unary   := ('+' | '-') unary | power
        power   := primary ('^' unary)?          # 오른쪽 결합: 2^3^2 = 2^9
        primary := 숫자(10진수/16진수/2진수) | '(' expr ')'
    """

    def __init__(self):
        self.tokens: List[Tuple[str, object]] = []
        self.pos = 0

    def tokenize(self, expr: str) -> List[Tuple[str, object]]:
        tokens = []
        i, n = 0, len(expr)
        while i < n:
            c = expr[i]
            if c in ' \t':
                i += 1
            elif c in '+-*/%^()':
                tokens.append(('op', c))
                i += 1
            elif c == '0' and i + 1 < n and expr[i + 1] in 'xX':
                # 16진수 파싱 (0x... / 0X...)
                j = i + 2
                while j < n and expr[j] in '0123456789abcdefABCDEF':
                    j += 1
                if j == i + 2:
                    raise CalcError("16진수 '0x' 뒤에 숫자가 없습니다")
                tokens.append(('num', int(expr[i:j], 16)))
                i = j
            elif c == '0' and i + 1 < n and expr[i + 1] in 'bB':
                # 2진수 파싱 (0b... / 0B...)
                j = i + 2
                while j < n and expr[j] in '01':
                    j += 1
                if j == i + 2:
                    raise CalcError("2진수 '0b' 뒤에 숫자가 없습니다 (0 또는 1)")
                tokens.append(('num', int(expr[i:j], 2)))
                i = j
            elif c.isdigit() or c == '.':
                # 10진수 (정수 또는 실수)
                j = i
                has_dot = False
                while j < n and (expr[j].isdigit() or expr[j] == '.'):
                    if expr[j] == '.':
                        if has_dot:
                            raise CalcError("숫자에 소수점이 2개 이상 있습니다")
                        has_dot = True
                    j += 1
                s = expr[i:j]
                if s == '.':
                    raise CalcError("잘못된 소수점 입력입니다")
                tokens.append(('num', float(s) if has_dot else int(s)))
                i = j
            else:
                raise CalcError(f"사용할 수 없는 문자: '{c}'")
        return tokens

    def _peek(self) -> Tuple[str, object]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ('eof', '')

    def _get(self) -> Tuple[str, object]:
        tok = self._peek()
        self.pos += 1
        return tok

    def _primary(self) -> Number:
        tok_type, val = self._peek()
        if tok_type == 'num':
            self._get()
            return val
        if tok_type == 'op' and val == '(':
            self._get()
            result = self._expr()
            if self._peek() != ('op', ')'):
                raise CalcError("닫는 괄호 ')'가 빠졌습니다")
            self._get()
            return result
        if tok_type == 'eof':
            raise CalcError("수식이 완성되지 않았습니다")
        raise CalcError(f"'{val}' 위치가 올바르지 않습니다")

    def _power(self) -> Number:
        base = self._primary()
        if self._peek() == ('op', '^'):
            self._get()
            exp = self._unary()   # 오른쪽 결합
            base = self._eval_pow(base, exp)
        return base

    def _unary(self) -> Number:
        tok_type, val = self._peek()
        if tok_type == 'op' and val in ('+', '-'):
            self._get()
            operand = self._unary()
            return -operand if val == '-' else operand
        return self._power()

    def _term(self) -> Number:
        left = self._unary()
        while True:
            tok_type, op = self._peek()
            if tok_type == 'op' and op in ('*', '/', '%'):
                self._get()
                right = self._unary()
                if op == '*':
                    left = left * right
                elif op == '/':
                    if right == 0:
                        raise CalcError("0으로 나눌 수 없습니다")
                    if isinstance(left, int) and isinstance(right, int) and left % right == 0:
                        left = left // right
                    else:
                        left = left / right
                elif op == '%':
                    if right == 0:
                        raise CalcError("0으로 나눈 나머지는 계산할 수 없습니다")
                    left = left % right
            else:
                break
        return left

    def _expr(self) -> Number:
        left = self._term()
        while True:
            tok_type, op = self._peek()
            if tok_type == 'op' and op in ('+', '-'):
                self._get()
                right = self._term()
                left = (left + right) if op == '+' else (left - right)
            else:
                break
        return left

    def _eval_pow(self, base: Number, exp: Number) -> Number:
        if isinstance(base, int) and isinstance(exp, int):
            if exp < 0:
                return base ** exp   # 역수는 float
            if exp > MAX_POW_EXPONENT:
                raise CalcError(f"거듭제곱 지수가 너무 큽니다 (최대 {MAX_POW_EXPONENT})")
            if base in (0, 1):
                return base ** exp
            if base == -1:
                return 1 if exp % 2 == 0 else -1
            digits_estimate = exp * math.log10(abs(base))
            if digits_estimate > MAX_RESULT_BITS * 0.30103 + 5:
                raise CalcError("거듭제곱 결과가 너무 큽니다")
            return base ** exp

        try:
            result = base ** exp
        except OverflowError:
            raise CalcError("거듭제곱 결과가 너무 큽니다")
        if isinstance(result, complex):
            raise CalcError("음수의 분수 거듭제곱은 계산할 수 없습니다")
        return result

    def math_result(self, expr: str) -> Number:
        """수식 계산 결과 반환. 문법 오류 시 CalcError 발생"""
        self.tokens = self.tokenize(expr)
        self.pos = 0
        if not self.tokens:
            raise CalcError("수식을 입력하세요")
        try:
            value = self._expr()
        except OverflowError:
            raise CalcError("숫자가 너무 큽니다")
        if self.pos < len(self.tokens):
            raise CalcError(f"'{self.tokens[self.pos][1]}' 위치가 올바르지 않습니다")
        if isinstance(value, int) and value.bit_length() > MAX_RESULT_BITS:
            raise CalcError(f"결과가 너무 큽니다 ({MAX_RESULT_BITS}비트 초과)")
        if isinstance(value, float):
            if not math.isfinite(value):
                raise CalcError("숫자가 너무 큽니다")
            if value.is_integer() and abs(value) < 2 ** 53:
                value = int(value)   # 2.5*2 → 5
        return value


def to_hex(value: int) -> str:
    """정수를 16진수로 포맷 (음수는 -0x 표기)"""
    return f"-0x{-value:X}" if value < 0 else f"0x{value:X}"


def format_value_str(value: Number) -> str:
    """계산 결과 값을 문자열로 변환 (정수는 16진수 병기, 실수는 순수 10진수)"""
    if isinstance(value, int):
        return f"{value} ( {to_hex(value)} )"
    if value.is_integer():
        ival = int(value)
        return f"{ival} ( {to_hex(ival)} )"
    return f"{value:.15g}"


def format_result(expr: str, value: Number) -> str:
    """결과 문자열 포맷: 수식 = 결과값"""
    return f"{expr} = {format_value_str(value)}"


###############################################################################################
# 커스텀 위젯: 히스토리 입력창 및 인라인 계산 메모장
###############################################################################################
class HistoryLineEdit(QLineEdit):
    """위/아래 방향키로 이전 입력 수식 히스토리를 탐색하는 QLineEdit"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: List[str] = []
        self.history_index: int = -1
        self.saved_text: str = ""

    def add_history(self, text: str):
        """새 수식을 히스토리에 추가"""
        text = text.strip()
        if not text:
            return
        if self.history and self.history[-1] == text:
            self.history_index = -1
            return
        if text in self.history:
            self.history.remove(text)
        self.history.append(text)
        if len(self.history) > 100:
            self.history.pop(0)
        self.history_index = -1

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key == Qt.Key_Up:
            if not self.history:
                super().keyPressEvent(event)
                return
            if self.history_index == -1:
                self.saved_text = self.text()
                self.history_index = len(self.history) - 1
            elif self.history_index > 0:
                self.history_index -= 1
            self.setText(self.history[self.history_index])
            self.selectAll()
            event.accept()
            return
        elif key == Qt.Key_Down:
            if self.history_index != -1:
                if self.history_index < len(self.history) - 1:
                    self.history_index += 1
                    self.setText(self.history[self.history_index])
                    self.selectAll()
                else:
                    self.history_index = -1
                    self.setText(self.saved_text)
                event.accept()
                return
        elif key == Qt.Key_Escape:
            if self.history_index != -1:
                self.history_index = -1
                self.setText(self.saved_text)
                event.accept()
                return
        super().keyPressEvent(event)


class MemoEdit(QTextEdit):
    """인라인 수식 계산(Ctrl+Enter / F5) 및 단축키를 직접 처리하는 QTextEdit"""

    def __init__(self, main_window: 'MainWindow', parent=None):
        super().__init__(parent)
        self.main_window = main_window

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)

        # Ctrl+Enter 또는 F5: 메모장 내 인라인 계산
        if (ctrl and key in (Qt.Key_Return, Qt.Key_Enter)) or (not ctrl and key == Qt.Key_F5):
            self.main_window.evaluate_inline()
            event.accept()
            return

        # Ctrl + Up/Down/+/=: 글꼴 크기 변경
        if ctrl and key in (Qt.Key_Up, Qt.Key_Plus, Qt.Key_Equal):
            self.main_window.change_font_size(1)
            event.accept()
            return
        if ctrl and key in (Qt.Key_Down, Qt.Key_Minus):
            self.main_window.change_font_size(-1)
            event.accept()
            return

        # F-키 전달 (F1, F4, F6, F10, F12)
        if key in (Qt.Key_F1, Qt.Key_F4, Qt.Key_F6, Qt.Key_F10, Qt.Key_F12) or (ctrl and key == Qt.Key_T):
            self.main_window.keyPressEvent(event)
            event.accept()
            return

        super().keyPressEvent(event)


###############################################################################################
# 메인 윈도우 UI
###############################################################################################
class MainWindow(QMainWindow):
    """Smart MemoPad 메인 윈도우"""

    DATA_FILE = os.path.join(get_app_path(), "smart_memopad_data.txt")
    LEGACY_FILE = os.path.join(get_app_path(), "expression_calculator_temp.txt")
    INI_FILE = os.path.join(get_app_path(), "smart_memopad.ini")
    DEFAULT_FONT = "Consolas"
    AUTOSAVE_MS = 2000

    def __init__(self):
        super().__init__()
        self.calculator = MathCalculator()
        self.font_size = 12
        self.dark_mode = True
        self.ini_lines: List[str] = []
        self.ini_encoding = "utf-8"
        self.save_error_shown = False

        self.init_ui()
        self.load_settings()
        self.apply_theme(self.dark_mode)
        self.load_temp_memo()

    @property
    def backup_file(self) -> str:
        return os.path.splitext(self.DATA_FILE)[0] + ".bak"

    def init_ui(self):
        """UI 컴포넌트 초기화 및 배치"""
        self.setWindowTitle("Smart MemoPad - 수식 계산 메모장")
        self.setGeometry(100, 100, 700, 530)
        self.setMinimumSize(480, 340)

        # 아이콘 설정
        if os.path.exists(ICON_PATH):
            self.setWindowIcon(QIcon(ICON_PATH))

        # 기본 항상 위 설정 (Ctrl+T 로 토글 가능)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # 메인 위젯 및 레이아웃
        central_widget = QWidget()
        central_widget.setObjectName("centralWidget")
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 상단 수식 입력 영역 (히스토리 지원)
        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        self.ed_input = HistoryLineEdit()
        self.ed_input.setPlaceholderText("수식 입력 (예: 1+2*3, 0xFF+1, 0b1010+2, 2^8) [↑/↓ 히스토리]")
        self.ed_input.setFont(QFont("Consolas", 13))
        self.ed_input.returnPressed.connect(self.btn_run_click)
        input_layout.addWidget(self.ed_input, 1)

        self.btn_run = QPushButton("=")
        self.btn_run.setFixedWidth(54)
        self.btn_run.setFont(QFont("Consolas", 13, QFont.Bold))
        self.btn_run.setToolTip("수식 계산 실행 (Enter)")
        self.btn_run.clicked.connect(self.btn_run_click)
        input_layout.addWidget(self.btn_run)

        layout.addLayout(input_layout)

        # 중앙 메모 영역 (인라인 계산 및 폰트 크기 변경 지원)
        self.memo_note = MemoEdit(self)
        self.memo_note.setFont(QFont(self.DEFAULT_FONT, self.font_size))
        self.memo_note.setPlaceholderText(
            "메모를 자유롭게 작성하세요...\n"
            "- 줄 어디서나 Ctrl+Enter 또는 F5 를 누르면 해당 수식이 인라인으로 바로 계산됩니다.\n"
            "- 상단 입력창에서 수식 입력 후 Enter 를 누르면 메모 끝에 결과가 덧붙여집니다."
        )
        self.memo_note.setLineWrapMode(QTextEdit.WidgetWidth)
        self.memo_note.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.memo_note.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        layout.addWidget(self.memo_note, 1)

        # 자동 저장 타이머: 입력 멈추고 2초 후 자동 저장
        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(self.AUTOSAVE_MS)
        self.autosave_timer.timeout.connect(self.save_temp_memo)
        self.memo_note.textChanged.connect(self.autosave_timer.start)

        # 하단 상태 표시줄
        self.status_guide = QLabel("F1:도움말 | F4:지우기 | F5/Ctrl+Enter:계산 | F6:테마 | F10:저장 | Ctrl+↑↓:폰트 | Ctrl+T:항상 위")
        self.statusBar().addPermanentWidget(self.status_guide)

    def apply_theme(self, dark: bool):
        """다크 / 라이트 테마 스타일시트 적용"""
        self.dark_mode = dark
        if dark:
            self.setStyleSheet("""
                QMainWindow { background-color: #1e1e1e; }
                QWidget#centralWidget { background-color: #1e1e1e; }
            """)
            self.ed_input.setStyleSheet("""
                QLineEdit {
                    background-color: #1e1e1e;
                    color: #ffffff;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    padding: 6px 10px;
                }
                QLineEdit:focus { border: 1px solid #007acc; }
            """)
            self.btn_run.setStyleSheet("""
                QPushButton {
                    background-color: #0e639c;
                    color: #ffffff;
                    border: 1px solid #1177bb;
                    border-radius: 4px;
                    padding: 6px;
                }
                QPushButton:hover { background-color: #1177bb; }
                QPushButton:pressed { background-color: #094771; }
            """)
            self.memo_note.setStyleSheet("""
                QTextEdit {
                    background-color: #252526;
                    color: #d4d4d4;
                    border: 1px solid #3c3c3c;
                    border-radius: 4px;
                    padding: 8px;
                    selection-background-color: #264f78;
                }
            """)
            self.statusBar().setStyleSheet("QStatusBar { color: #cccccc; background-color: #1e1e1e; }")
            if self.status_guide:
                self.status_guide.setStyleSheet("color: #888888; font-size: 11px;")
        else:
            self.setStyleSheet("""
                QMainWindow { background-color: #f3f3f3; }
                QWidget#centralWidget { background-color: #f3f3f3; }
            """)
            self.ed_input.setStyleSheet("""
                QLineEdit {
                    background-color: #ffffff;
                    color: #1e1e1e;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 6px 10px;
                }
                QLineEdit:focus { border: 1px solid #0078d4; }
            """)
            self.btn_run.setStyleSheet("""
                QPushButton {
                    background-color: #0078d4;
                    color: #ffffff;
                    border: 1px solid #005a9e;
                    border-radius: 4px;
                    padding: 6px;
                }
                QPushButton:hover { background-color: #106ebe; }
                QPushButton:pressed { background-color: #004578; }
            """)
            self.memo_note.setStyleSheet("""
                QTextEdit {
                    background-color: #ffffff;
                    color: #1e1e1e;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 8px;
                    selection-background-color: #add6ff;
                }
            """)
            self.statusBar().setStyleSheet("QStatusBar { color: #333333; background-color: #e5e5e5; }")
            if self.status_guide:
                self.status_guide.setStyleSheet("color: #666666; font-size: 11px;")

    def toggle_theme(self):
        """테마 전환 (F6)"""
        self.apply_theme(not self.dark_mode)
        self.save_settings()
        self.notify(f"테마 전환: {'다크 모드' if self.dark_mode else '라이트 모드'}")

    def center_window(self):
        """현재 마우스/화면 중앙에 윈도우 배치"""
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        rect = self.frameGeometry()
        rect.moveCenter(screen.availableGeometry().center())
        self.move(rect.topLeft())

    def notify(self, message: str, ms: int = 5000):
        """상태 표시줄에 일시적 메시지 출력"""
        self.statusBar().showMessage(message, ms)

    ###########################################################################################
    # 환경 설정 (ini)
    ###########################################################################################
    def load_settings(self):
        """설정 파일 로드 (글꼴, 글꼴 크기, 테마 복원)"""
        if not os.path.exists(self.INI_FILE):
            return
        try:
            with open(self.INI_FILE, 'rb') as f:
                raw = f.read()
        except OSError:
            return

        for enc in ('utf-8', 'cp949'):
            try:
                self.ini_lines = raw.decode(enc).splitlines()
                self.ini_encoding = enc
                break
            except UnicodeDecodeError:
                continue
        else:
            self.notify("설정 파일을 읽지 못해 기본 글꼴을 사용합니다")
            return

        font_name = self.ini_lines[0].strip() if self.ini_lines else ""
        if font_name not in QFontDatabase.families():
            font_name = self.DEFAULT_FONT
        try:
            self.font_size = max(8, min(32, int(self.ini_lines[1].strip())))
        except (IndexError, ValueError):
            pass

        if len(self.ini_lines) >= 3:
            theme_val = self.ini_lines[2].strip().lower()
            if theme_val == 'light':
                self.dark_mode = False
            elif theme_val == 'dark':
                self.dark_mode = True

        self.memo_note.setFont(QFont(font_name, self.font_size))

    def save_settings(self):
        """설정 파일 저장 (ini)"""
        lines = list(self.ini_lines) or [self.DEFAULT_FONT]
        while len(lines) < 3:
            lines.append("")
        lines[0] = self.memo_note.font().family() or self.DEFAULT_FONT
        lines[1] = str(self.font_size)
        lines[2] = "dark" if self.dark_mode else "light"
        try:
            with open(self.INI_FILE, 'w', encoding=self.ini_encoding, newline='\r\n') as f:
                f.write("\n".join(lines) + "\n")
            self.ini_lines = lines
        except OSError:
            pass

    ###########################################################################################
    # 계산 실행 (상단 입력창 및 인라인)
    ###########################################################################################
    def btn_run_click(self):
        """상단 입력창 계산 실행: 결과는 메모장 끝에 추가, 히스토리에 기록"""
        expr = self.ed_input.text().strip()
        if not expr:
            return
        try:
            value = self.calculator.math_result(expr)
        except CalcError as e:
            self.notify(f"계산 오류: {e}")
            self.ed_input.selectAll()
            return

        self.ed_input.add_history(expr)
        self.memo_note.append(format_result(" ".join(expr.split()), value))
        self.ed_input.selectAll()

    def evaluate_inline(self):
        """메모장 내 수식 인라인 계산 (선택 영역 또는 현재 줄 계산 후 즉시 삽입)"""
        cursor = self.memo_note.textCursor()

        # 1. 텍스트가 선택되어 있는 경우
        if cursor.hasSelection():
            raw = cursor.selectedText().replace('\u2029', '\n').strip()
            if raw.endswith('='):
                expr = raw[:-1].strip()
                append_mode = 'space'
            elif '=' in raw:
                parts = raw.rsplit('=', 1)
                expr = parts[0].strip()
                append_mode = 'replace'
            else:
                expr = raw
                append_mode = 'equal'

            try:
                val = self.calculator.math_result(expr)
            except CalcError as e:
                self.notify(f"인라인 계산 오류: {e}")
                return

            val_str = format_value_str(val)
            if append_mode == 'replace':
                cursor.insertText(f"{expr} = {val_str}")
            elif append_mode == 'space':
                cursor.setPosition(cursor.selectionEnd())
                cursor.insertText(f" {val_str}")
            else:
                cursor.setPosition(cursor.selectionEnd())
                cursor.insertText(f" = {val_str}")
            self.memo_note.setTextCursor(cursor)
            self.notify(f"계산 완료: {expr} = {val_str}")
            return

        # 2. 선택이 없는 경우: 커서가 위치한 줄 전체 분석
        block = cursor.block()
        line_text = block.text()
        stripped = line_text.strip()
        if not stripped:
            return

        target_text = ""
        # 2-1. 줄 안에 '=' 가 있는 경우
        if '=' in line_text:
            left, right = line_text.rsplit('=', 1)
            left_s = left.strip()
            right_s = right.strip()
            if not right_s:   # 예: '10 + 20 ='
                try:
                    val = self.calculator.math_result(left_s)
                    val_str = format_value_str(val)
                    target_text = f"{left_s} = {val_str}"
                except CalcError:
                    pass
            else:
                # 이미 계산된 줄 재계산 (예: '10 + 20 = 30')
                try:
                    val = self.calculator.math_result(left_s)
                    val_str = format_value_str(val)
                    target_text = f"{left_s} = {val_str}"
                except CalcError:
                    # 변수 할당 스타일 (예: 'a = 10 + 20')
                    try:
                        val = self.calculator.math_result(right_s)
                        val_str = format_value_str(val)
                        target_text = f"{line_text} = {val_str}"
                    except CalcError:
                        pass

        # 2-2. 줄 안에 ':' 가 있는 경우 (예: '점심값: 7000 + 1500')
        if not target_text and ':' in line_text:
            left, right = line_text.rsplit(':', 1)
            try:
                val = self.calculator.math_result(right.strip())
                val_str = format_value_str(val)
                target_text = f"{line_text} = {val_str}"
            except CalcError:
                pass

        # 2-3. 일반 수식 줄인 경우 (예: '10 + 20')
        if not target_text:
            try:
                val = self.calculator.math_result(stripped)
                val_str = format_value_str(val)
                target_text = f"{line_text} = {val_str}"
            except CalcError as e:
                self.notify(f"인라인 계산 오류: {e}")
                return

        # 줄 텍스트 교체 (개행 보존)
        cursor.setPosition(block.position())
        cursor.setPosition(block.position() + len(line_text), QTextCursor.KeepAnchor)
        cursor.insertText(target_text)
        self.memo_note.setTextCursor(cursor)
        self.notify(f"계산 완료: {target_text.strip()}")

    ###########################################################################################
    # 단축키 및 이벤트
    ###########################################################################################
    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)

        if key == Qt.Key_F1:
            self.show_help()
        elif key == Qt.Key_F4:
            self.clear_memo()
        elif key == Qt.Key_F5:
            self.evaluate_inline()
        elif key == Qt.Key_F6:
            self.toggle_theme()
        elif key == Qt.Key_F10:
            self.save_results()
        elif key == Qt.Key_F12:
            self.memo_note.selectAll()
        elif ctrl and key in (Qt.Key_Up, Qt.Key_Plus, Qt.Key_Equal):
            self.change_font_size(1)
        elif ctrl and key in (Qt.Key_Down, Qt.Key_Minus):
            self.change_font_size(-1)
        elif ctrl and key == Qt.Key_T:
            self.toggle_always_on_top()
        else:
            super().keyPressEvent(event)

    def clear_memo(self):
        """메모 전체 지우기 (확인 대화상자 + Undo Ctrl+Z 지원)"""
        if not self.memo_note.toPlainText().strip():
            return
        reply = QMessageBox.question(
            self, "메모 지우기",
            "메모를 모두 지울까요?\n(지운 후에도 Ctrl+Z 로 되돌릴 수 있습니다)",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        cursor = self.memo_note.textCursor()
        cursor.select(QTextCursor.Document)
        cursor.removeSelectedText()
        self.notify("메모를 지웠습니다 (Ctrl+Z 로 되돌리기 가능)")

    def toggle_always_on_top(self):
        """항상 위에 표시 켜기/끄기"""
        on = not bool(self.windowFlags() & Qt.WindowStaysOnTopHint)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()
        self.notify(f"항상 위에 표시: {'켜짐' if on else '꺼짐'}")

    def show_help(self):
        """도움말 안내 창"""
        help_text = (
            "Smart MemoPad - 수식 계산 메모장\n\n"
            "[주요 단축키]\n"
            "  F1             : 도움말 표시\n"
            "  F4             : 메모 전체 지우기 (Ctrl+Z 로 실행 취소 가능)\n"
            "  F5 / Ctrl+Enter: 메모장 내 수식 인라인 계산 (선택 영역 또는 현재 줄)\n"
            "  F6             : 다크 / 라이트 테마 전환\n"
            "  F10            : 메모를 외부 파일로 저장\n"
            "  F12            : 메모 전체 선택\n"
            "  Ctrl+↑ / ↓     : 글꼴 크기 확대/축소 (기존 메모 실시간 반영 및 설정 보존)\n"
            "  Ctrl+T         : 항상 위에 표시 토글\n"
            "  ↑ / ↓ (입력창) : 상단 수식 입력창에서 이전 입력 기록(히스토리) 탐색\n\n"
            "[지원 연산자 (우선순위 순)]\n"
            "  ^              : 거듭제곱 (오른쪽 결합: 2^3^2 = 2^9 = 512)\n"
            "  + -            : 부호 (+5, -10, 2*-3)\n"
            "  * / %          : 곱셈, 나눗셈, 나머지\n"
            "  + -            : 덧셈, 뺄셈\n"
            "  ( )            : 괄호 연산\n\n"
            "[진법 및 수식 입력 예시]\n"
            "  1 + 2 * 3 = 7\n"
            "  -5 + 3 = -2\n"
            "  1 / 2 = 0.5 (실수는 순수 10진수만 표시)\n"
            "  10 * 7 % 4 = 2\n"
            "  2 ^ 8 = 256\n"
            "  0xFF + 1 = 256 ( 0x100 )\n"
            "  0b1010 + 2 = 12 ( 0xC ) (2진수 지원)\n"
            "  0x1000 - 0x10 = 4080 ( 0xFF0 )\n"
            "  0xFFFFFFFFFFFFFFFF = 18446744073709551615\n\n"
            "[자동 저장 & 백업]\n"
            "  입력이 멈추고 2초 뒤 자동 저장되며,\n"
            "  이전 세션의 메모는 .bak 파일로 안전하게 보관됩니다."
        )
        QMessageBox.information(self, "도움말", help_text)

    def save_results(self):
        """메모를 외부 텍스트 파일로 내보내기"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "메모 내보내기", "", "텍스트 파일 (*.txt)"
        )
        if file_path:
            if not file_path.endswith('.txt'):
                file_path += '.txt'
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(self.memo_note.toPlainText())
                QMessageBox.information(self, "저장 완료", f"파일이 저장되었습니다:\n{file_path}")
            except Exception as e:
                QMessageBox.warning(self, "저장 실패", f"파일 저장 중 오류 발생:\n{e}")

    def change_font_size(self, delta: int):
        """글꼴 크기 조절 (기존 작성된 텍스트 및 신규 입력 모두에 실시간 즉시 반영)"""
        self.font_size = max(8, min(32, self.font_size + delta))
        font = self.memo_note.font()
        font.setPointSize(self.font_size)
        self.memo_note.setFont(font)

        # 기존 HTML 형식 텍스트 전체의 폰트 크기 일괄 갱신
        old_cursor = self.memo_note.textCursor()
        cursor = self.memo_note.textCursor()
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setFontPointSize(self.font_size)
        cursor.mergeCharFormat(fmt)
        self.memo_note.setTextCursor(old_cursor)

        self.save_settings()
        self.notify(f"글꼴 크기: {self.font_size}pt")

    ###########################################################################################
    # 메모 자동 저장 & 세션 복원
    ###########################################################################################
    def load_temp_memo(self):
        """이전 메모 복원 및 직전 세션 백업(.bak)"""
        target_file = self.DATA_FILE
        if not os.path.exists(target_file) and os.path.exists(self.LEGACY_FILE):
            target_file = self.LEGACY_FILE

        if not os.path.exists(target_file):
            return

        try:
            with open(target_file, 'rb') as f:
                raw = f.read()
        except OSError:
            return

        content = None
        for enc in ('utf-8', 'cp949'):
            try:
                content = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            broken = self.DATA_FILE + datetime.now().strftime(".broken_%Y%m%d_%H%M%S")
            try:
                os.replace(target_file, broken)
                QMessageBox.warning(
                    self, "메모 복원 실패",
                    f"메모 파일을 읽을 수 없어 다른 이름으로 보관했습니다:\n{broken}"
                )
            except OSError:
                pass
            return

        try:
            shutil.copy2(target_file, self.backup_file)
        except OSError:
            pass

        self.memo_note.blockSignals(True)
        if content.lstrip().startswith('<'):
            self.memo_note.setHtml(content)
        else:
            self.memo_note.setPlainText(content)
        self.memo_note.blockSignals(False)

        self.memo_note.document().clearUndoRedoStacks()
        self.memo_note.moveCursor(QTextCursor.End)

    def save_temp_memo(self) -> bool:
        """메모를 안전하게 임시 파일에 기록 후 원자적 교체(Atomic Rename)"""
        self.autosave_timer.stop()
        content = self.memo_note.toHtml() if self.memo_note.toPlainText().strip() else ""
        tmp_path = self.DATA_FILE + ".tmp"
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.DATA_FILE)
            self.save_error_shown = False
            return True
        except OSError as e:
            self.notify(f"메모 자동 저장 실패: {e}", 10000)
            if not self.save_error_shown:
                self.save_error_shown = True
                QMessageBox.warning(
                    self, "메모 저장 실패",
                    f"메모를 저장하지 못했습니다:\n{e}\n\nF10 키를 눌러 다른 위치에 저장해 두세요."
                )
            return False

    def closeEvent(self, event):
        """창 종료 시 최종 저장"""
        if not self.save_temp_memo():
            reply = QMessageBox.question(
                self, "메모 저장 실패",
                "메모를 저장하지 못했습니다. 그래도 종료할까요?\n(아니요를 누르고 F10 으로 저장할 수 있습니다)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
        self.save_settings()
        event.accept()


def main():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SmartMemoPad")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if os.path.exists(ICON_PATH):
        app.setWindowIcon(QIcon(ICON_PATH))

    window = MainWindow()
    window.center_window()
    window.show()
    window.raise_()
    window.activateWindow()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
