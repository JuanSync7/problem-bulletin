/**
 * v2.6-WP45: TicketDTO now narrows assignee_type to "user" | "agent" | null.
 *
 * This is primarily a TypeScript compile-time check (vitest only runs the
 * runtime assertion below; the compiler is the real gate). If the field is
 * removed or its union widened, this file fails to type-check.
 */
import { describe, it, expect } from "vitest";
import type { TicketDTO } from "../tickets";

describe("TicketDTO assignee_type", () => {
  it("accepts user / agent / null and is optional", () => {
    const human: TicketDTO = {
      id: "t1",
      title: "x",
      status: "todo",
      assignee_id: "u1",
      assignee_type: "user",
      version: 1,
    };
    const agent: TicketDTO = {
      id: "t2",
      title: "y",
      status: "todo",
      assignee_id: "a1",
      assignee_type: "agent",
      version: 1,
    };
    const unassigned: TicketDTO = {
      id: "t3",
      title: "z",
      status: "todo",
      assignee_type: null,
      version: 1,
    };
    const omitted: TicketDTO = { id: "t4", title: "w", status: "todo", version: 1 };

    expect(human.assignee_type).toBe("user");
    expect(agent.assignee_type).toBe("agent");
    expect(unassigned.assignee_type).toBeNull();
    expect(omitted.assignee_type).toBeUndefined();
  });
});
