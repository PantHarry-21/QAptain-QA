/**
 * @fileoverview
 * This file contains the Smart Form Filler utility, which generates realistic
 * fake data for form fields based on deterministic, context-aware rules.
 * It is designed to be a self-contained, local utility with no external dependencies.
 */

/**
 * Generates a realistic fake value for a form field based on its context.
 * The function prioritizes matching keywords in the field's label/name and
 * falls back to matching based on the field's HTML type attribute.
 *
 * @param fieldLabel - The combined text from the field's label, name, and placeholder, converted to lowercase.
 * @param fieldType - The `type` attribute of the input field (e.g., 'text', 'email', 'number').
 * @returns A string containing the generated fake data.
 *
 * @example
 * // Returns "harry@example.com"
 * generateFakeValue("user email address", "email");
 *
 * @example
 * // Returns "John Doe"
 * generateFakeValue("full_name", "text");
 *
 * @example
 * // Returns "42"
 * generateFakeValue("user_age", "number");
 */
export function generateFakeValue(fieldLabel: string, fieldType: string): string {
  const lowerLabel = fieldLabel.toLowerCase();

  // 1. Context Matching (most specific keywords first)
  if (lowerLabel.includes('email')) return 'harry@example.com';
  if (lowerLabel.includes('password')) return 'Harry@123';
  if (lowerLabel.includes('username')) return 'test_user';
  if (lowerLabel.includes('name')) return 'John Doe'; // Catches "full name", "first name", etc.
  if (lowerLabel.includes('phone') || lowerLabel.includes('mobile')) return '9876543210';
  if (lowerLabel.includes('address')) return '123 Main Street, NY';
  if (lowerLabel.includes('city')) return 'New York';
  if (lowerLabel.includes('zip') || lowerLabel.includes('postal')) return '10001';
  if (lowerLabel.includes('date')) return new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  if (lowerLabel.includes('quantity')) return '10';
  if (lowerLabel.includes('amount') || lowerLabel.includes('price')) return '500';

  // 2. Fallback Based on Input Type
  switch (fieldType) {
    case 'email':
      return 'harry@example.com';
    case 'number':
      return '42';
    case 'url':
      return 'https://example.com';
    case 'password':
      return 'Harry@123';
    default:
      return 'Sample Text';
  }
}
