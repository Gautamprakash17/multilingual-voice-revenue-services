/**
 * Unit checks for catalog-driven required-field validation.
 * Run: npm test
 */

import { describe, expect, it } from "vitest";
import type { ServiceFieldConfig } from "../api/client";
import {
  draftValueForBackend,
  findFirstMissingRequired,
  missingRequiredMessage,
} from "./form";

const incomeFields: ServiceFieldConfig[] = [
  { name: "applicant_name", type: "string", required: true },
  { name: "date_of_birth", type: "date", required: true },
  { name: "mobile_number", type: "mobile", required: true },
  { name: "address", type: "string", required: true },
  { name: "district", type: "string", required: true },
  { name: "annual_income", type: "number", required: true },
  { name: "income_source", type: "string", required: true },
];

function draft(partial: Record<string, string>) {
  const base: Record<string, string> = {};
  for (const field of incomeFields) base[field.name] = "";
  return { ...base, ...partial };
}

describe("catalog-driven required field validation", () => {
  it("blocks Save when full name is present but DOB is missing", () => {
    const missing = findFirstMissingRequired(
      incomeFields,
      draft({ applicant_name: "Gautam Prakash" }),
    );
    expect(missing?.name).toBe("date_of_birth");
    expect(missingRequiredMessage(missing!)).toBe("Please enter your date of birth.");
  });

  it("allows progress past DOB when DOB is present", () => {
    const missing = findFirstMissingRequired(
      incomeFields,
      draft({
        applicant_name: "Gautam Prakash",
        date_of_birth: "2018-01-02",
      }),
    );
    expect(missing?.name).not.toBe("date_of_birth");
  });

  it("blocks Save when any other required field is missing", () => {
    const missing = findFirstMissingRequired(
      incomeFields,
      draft({
        applicant_name: "Gautam Prakash",
        date_of_birth: "2018-01-02",
        mobile_number: "9876543210",
        district: "Bengaluru",
        annual_income: "120000",
        income_source: "Salary",
      }),
    );
    expect(missing?.name).toBe("address");
    expect(missingRequiredMessage(missing!)).toBe(
      "Please enter your residential address.",
    );
  });

  it("allows Save when all required catalog fields are present", () => {
    const missing = findFirstMissingRequired(
      incomeFields,
      draft({
        applicant_name: "Gautam Prakash",
        date_of_birth: "2018-01-02",
        mobile_number: "9876543210",
        address: "12 Temple Street",
        district: "Bengaluru",
        annual_income: "120000",
        income_source: "Salary",
      }),
    );
    expect(missing).toBeNull();
  });

  it("ignores optional fields when deciding required completeness", () => {
    const fields: ServiceFieldConfig[] = [
      { name: "applicant_name", type: "string", required: true },
      { name: "nickname", type: "string", required: false },
    ];
    const missing = findFirstMissingRequired(fields, {
      applicant_name: "Gautam",
      nickname: "",
    });
    expect(missing).toBeNull();
  });

  it("does not treat empty required values as completed backend values", () => {
    const dob = incomeFields.find((f) => f.name === "date_of_birth")!;
    expect(draftValueForBackend(dob, "")).toBe("");
    expect(draftValueForBackend(dob, "   ")).toBe("");
    expect(draftValueForBackend(dob, "2018-01-02")).toBe("02/01/2018");
  });
});
