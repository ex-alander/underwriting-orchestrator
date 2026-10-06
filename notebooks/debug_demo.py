from underwriting.credit_math import calc_payment


def main():
    principal = 1_000_000
    rate = 0.15
    months = 60

    breakpoint()  # <-- здесь отладчик остановится

    payment = calc_payment(principal, rate, months)
    print(f"Платёж: {payment:.2f}")


if __name__ == "__main__":
    main()
