import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { MAX_QUESTION_CHARS } from "./ask-workspace";

describe("question length limit", () => {
  it("matches max_question_length in config/sql_policy.yaml", () => {
    const policy = readFileSync(resolve(__dirname, "../../../config/sql_policy.yaml"), "utf-8");
    const match = policy.match(/^max_question_length:\s*(\d+)/m);
    expect(match).not.toBeNull();
    expect(MAX_QUESTION_CHARS).toBe(Number(match![1]));
  });
});
