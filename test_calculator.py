import unittest
from main import MathCalculator, CalcError, format_result


class TestMathCalculator(unittest.TestCase):
    def setUp(self):
        self.calc = MathCalculator()

    def test_basic_arithmetic(self):
        self.assertEqual(self.calc.math_result("1 + 2 * 3"), 7)
        self.assertEqual(self.calc.math_result("-5 + 3"), -2)
        self.assertEqual(self.calc.math_result("1 / 2"), 0.5)
        self.assertEqual(self.calc.math_result("10 - 3 - 2"), 5)

    def test_precedence_and_associativity(self):
        # 2^3^2 should evaluate as 2^(3^2) = 2^9 = 512 (Right-associative power)
        self.assertEqual(self.calc.math_result("2 ^ 3 ^ 2"), 512)
        # Power precedence over multiplication
        self.assertEqual(self.calc.math_result("2 * 3 ^ 2"), 18)
        # Unary minus before power
        self.assertEqual(self.calc.math_result("-2 ^ 2"), -4)
        self.assertEqual(self.calc.math_result("(-2) ^ 2"), 4)

    def test_modulo(self):
        self.assertEqual(self.calc.math_result("10 * 7 % 4"), 2)
        self.assertEqual(self.calc.math_result("15 % 4"), 3)

    def test_parentheses(self):
        self.assertEqual(self.calc.math_result("((10 % 6) * 2 / 4) ^ 8"), 256)
        self.assertEqual(self.calc.math_result("(2 + 3) * (4 - 1)"), 15)

    def test_hexadecimal(self):
        self.assertEqual(self.calc.math_result("0xFF + 1"), 256)
        self.assertEqual(self.calc.math_result("0x10 * 0x10"), 256)
        self.assertEqual(self.calc.math_result("0x1000 - 0x10"), 4080)
        # 64-bit max unsigned int
        self.assertEqual(self.calc.math_result("0xFFFFFFFFFFFFFFFF"), 18446744073709551615)

    def test_binary(self):
        # 2진수 리터럴 지원 (0b / 0B)
        self.assertEqual(self.calc.math_result("0b1010 + 2"), 12)
        self.assertEqual(self.calc.math_result("0B1111"), 15)
        self.assertEqual(self.calc.math_result("0b100000000"), 256)
        self.assertEqual(self.calc.math_result("0b1010 * 0b10"), 20)

    def test_negative_multiplication(self):
        self.assertEqual(self.calc.math_result("2 * -3"), -6)
        self.assertEqual(self.calc.math_result("-5 * -4"), 20)

    def test_format_result(self):
        # 정수는 16진수 표기 병기
        res1 = format_result("0xFF + 1", 256)
        self.assertEqual(res1, "0xFF + 1 = 256 ( 0x100 )")

        # 실수는 순수 10진수로만 표시 (불필요한 0x0 제거 검증)
        res2 = format_result("1 / 2", 0.5)
        self.assertEqual(res2, "1 / 2 = 0.5")

        # 2진수 연산 결과 포맷 검증
        res3 = format_result("0b1010 + 2", self.calc.math_result("0b1010 + 2"))
        self.assertEqual(res3, "0b1010 + 2 = 12 ( 0xC )")

    def test_errors(self):
        # Division by zero
        with self.assertRaises(CalcError):
            self.calc.math_result("1 / 0")
        with self.assertRaises(CalcError):
            self.calc.math_result("10 % 0")

        # Incomplete / invalid syntax
        with self.assertRaises(CalcError):
            self.calc.math_result("1 +")
        with self.assertRaises(CalcError):
            self.calc.math_result("(1 + 2")
        with self.assertRaises(CalcError):
            self.calc.math_result("0x")
        with self.assertRaises(CalcError):
            self.calc.math_result("0b")
        with self.assertRaises(CalcError):
            self.calc.math_result("0b102")
        with self.assertRaises(CalcError):
            self.calc.math_result("1.2.3")
        with self.assertRaises(CalcError):
            self.calc.math_result("")


if __name__ == "__main__":
    unittest.main(verbosity=2)
