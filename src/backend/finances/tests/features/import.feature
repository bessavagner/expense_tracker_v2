Feature: CSV import wizard
  As a user migrating from Google Sheets
  I want to import my expense history from CSV files
  So I can have all my data in the new system

  Scenario: Import regular entries from CSV
    Given a logged-in user with seed data
    And a CSV file with 3 regular entries
    When I upload the CSV as regular entries
    And I confirm the column mapping
    And I execute the import
    Then 3 entries should exist in the database

  Scenario: Import installments from CSV
    Given a logged-in user with seed data
    And a CSV file with 1 installment of 2 parcels
    When I upload the CSV as installments
    And I confirm the column mapping
    And I execute the import
    Then 1 installment plan should exist
    And 2 installment entries should exist
