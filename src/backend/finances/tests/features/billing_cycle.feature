Feature: Billing cycle computation
  As a user with credit cards
  I want expenses to be assigned to the correct billing month
  Based on the credit card closing day

  Scenario: Pix purchase stays in current month
    Given a user with payment method "Pix" of type "pix"
    When I create an expense on "2026-03-15" with that payment method
    Then the billing month should be "2026-03-01"

  Scenario: Credit card purchase before closing day
    Given a user with a credit card closing on day 25
    When I create an expense on "2026-03-20" with that payment method
    Then the billing month should be "2026-03-01"

  Scenario: Credit card purchase after closing day
    Given a user with a credit card closing on day 25
    When I create an expense on "2026-03-26" with that payment method
    Then the billing month should be "2026-04-01"

  Scenario: Credit card purchase on closing day
    Given a user with a credit card closing on day 25
    When I create an expense on "2026-03-25" with that payment method
    Then the billing month should be "2026-03-01"

  Scenario: December purchase after closing rolls to January
    Given a user with a credit card closing on day 25
    When I create an expense on "2025-12-31" with that payment method
    Then the billing month should be "2026-01-01"
