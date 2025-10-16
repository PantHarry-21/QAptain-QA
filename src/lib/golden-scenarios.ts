/**
 * @fileoverview
 * This file contains a collection of "golden" or predefined test scenarios.
 * The test executor will check against these scenarios and, if a title matches,
 * it will use these predefined steps instead of the AI-generated ones.
 * This ensures that critical, common test paths are always executed consistently.
 */

interface GoldenScenario {
  title: string;
  steps: string[];
}

export const goldenScenarios: GoldenScenario[] = [
  {
    title: "Invalid login test",
    steps: [
      'Fill "abc.com" into the "email" field',
      'Click the "Login" button',
      'Verify that the page contains "Please enter a valid email address"'
    ]
  },
  {
    title: "Valid email and invalid password login test",
    steps: [
      'Fill "himanshupant.qa@gmail.com" into the "email" field',
      'Fill "12345" into the "password" field',
      'Click the "Login" button',
      'Verify that the page contains "Incorrect password"'
    ]
  },
  {
    title: "Valid login test",
    steps: [
      'Fill "himanshu.pant@tynybay.com" into the "email" field',
      'Fill "Harry@123" into the "password" field',
      'Click the "Login" button',
      'Verify that the page contains "Welcome to your Dashboard"'
    ]
  },
  // You can add more scenarios here...
  // {
  //   title: "Example: Navigate to another page",
  //   steps: [
  //     'Click the "Dashboard" link',
  //     'Verify that the page contains "Welcome to your Dashboard"'
  //   ]
  // },
];
