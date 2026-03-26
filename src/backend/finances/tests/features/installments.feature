Feature: Installment plan management
  As a user making installment purchases
  I want the system to generate individual entries for each installment
  So I can track monthly payments correctly

  Scenario: Create a 3-installment plan
    Given a user with a credit card closing on day 30
    And a category "Trabalho"
    When I create an installment plan for R$ 600.00 in 3 installments
    Then 3 entries should be created
    And each entry should have amount R$ 200.00
    And entries should have sequential billing months

  Scenario: Rounding remainder goes to last installment
    Given a user with a credit card closing on day 30
    And a category "Casa"
    When I create an installment plan for R$ 100.00 in 3 installments at R$ 33.33 each
    Then the last entry should have amount R$ 33.34
    And the total of all entries should equal R$ 100.00
