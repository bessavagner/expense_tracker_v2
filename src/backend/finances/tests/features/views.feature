Feature: Expense tracker views
  As a user managing personal finances
  I want to view, create, and edit entries through the web interface

  Scenario: View entries for a specific month
    Given a logged-in user with entries in March 2026
    When I visit the entries page for March 2026
    Then I should see only March entries
    And I should see a summary with total expenses

  Scenario: Create entry via inline form
    Given a logged-in user with categories and payment methods
    When I submit an inline entry for "Supermercado" with amount 150.00
    Then the entry should be created
    And the entry should appear in the table

  Scenario: Create installment via modal
    Given a logged-in user with a credit card closing on day 25
    When I create a 3-installment plan for R$ 600.00
    Then 3 installment entries should be created
    And the first billing month should be the computed month

  Scenario: View consolidated expenses by category
    Given a logged-in user with entries in multiple categories
    When I visit the consolidated page for 2026
    Then I should see category totals per month
    And categories over budget should be highlighted

  Scenario: Change category budget in settings
    Given a logged-in user with a category "Alimentação" with ceiling 1300
    When I change the budget ceiling to 1500
    Then the ceiling should be updated to 1500
