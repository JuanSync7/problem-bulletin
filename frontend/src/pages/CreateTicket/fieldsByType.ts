/**
 * Single source of truth for Create-Ticket form field rules per ticket type.
 *
 * Drives BOTH visibility AND validation in `CreateTicket.tsx` — no duplicated
 * rules in the JSX. WP3 lessons-learned recommendation #3:
 *
 *   "Per-type field-visibility rules from spec §5 map directly to the v2
 *    TicketCreate schema. Required-when-type rules to mirror in TS"
 *
 * Parent-type matrix mirrors `_PARENT_ALLOWED` in
 * `app/services/ticket_hierarchy.py` (or `app/services/tickets.py`) so the UI
 * never lets a user select an illegal parent before submit.
 */

export type TicketTypeV2 =
  | "workpackage"
  | "epic"
  | "story"
  | "task"
  | "bug"
  | "subtask";

export interface FieldSpec {
  required: boolean;
  visible: boolean;
}

export interface TypeFieldSpec {
  title: FieldSpec;
  description: FieldSpec;
  /** Always required — kept in the spec for parity / future flexibility. */
  project: FieldSpec;
  parent: FieldSpec;
  /** Empty array = no parent allowed (workpackage). */
  parentAllowedTypes: TicketTypeV2[];
  sprint: FieldSpec;
  component: FieldSpec;
  assignee: FieldSpec;
  priority: FieldSpec;
  /** Hidden on workpackage and subtask per spec §5. */
  storyPoints: FieldSpec;
  labels: FieldSpec;
  fixVersions: FieldSpec;
  dueDate: FieldSpec;
}

const visible = (required = false): FieldSpec => ({ required, visible: true });
const hidden: FieldSpec = { required: false, visible: false };

export const ALL_TICKET_TYPES: TicketTypeV2[] = [
  "workpackage",
  "epic",
  "story",
  "task",
  "bug",
  "subtask",
];

export const FIELDS_BY_TYPE: Record<TicketTypeV2, TypeFieldSpec> = {
  workpackage: {
    title: visible(true),
    description: visible(false),
    project: visible(true),
    parent: hidden,
    parentAllowedTypes: [],
    sprint: hidden,
    component: visible(false),
    assignee: visible(false),
    priority: visible(false),
    storyPoints: hidden,
    labels: visible(false),
    fixVersions: visible(false),
    dueDate: visible(false),
  },
  epic: {
    title: visible(true),
    description: visible(true),
    project: visible(true),
    parent: visible(false),
    parentAllowedTypes: ["workpackage"],
    sprint: visible(false),
    component: visible(false),
    assignee: visible(false),
    priority: visible(true),
    storyPoints: hidden,
    labels: visible(false),
    fixVersions: visible(false),
    dueDate: visible(false),
  },
  story: {
    title: visible(true),
    description: visible(true),
    project: visible(true),
    parent: visible(false),
    parentAllowedTypes: ["epic", "workpackage"],
    sprint: visible(false),
    component: visible(false),
    assignee: visible(false),
    priority: visible(true),
    storyPoints: visible(false),
    labels: visible(false),
    fixVersions: visible(false),
    dueDate: visible(false),
  },
  task: {
    title: visible(true),
    description: visible(false),
    project: visible(true),
    parent: visible(false),
    parentAllowedTypes: ["story", "epic", "workpackage"],
    sprint: visible(false),
    component: visible(false),
    assignee: visible(false),
    priority: visible(true),
    storyPoints: visible(false),
    labels: visible(false),
    fixVersions: visible(false),
    dueDate: visible(false),
  },
  bug: {
    title: visible(true),
    description: visible(true),
    project: visible(true),
    parent: visible(false),
    parentAllowedTypes: ["story", "epic", "workpackage"],
    sprint: visible(false),
    component: visible(false),
    assignee: visible(false),
    priority: visible(true),
    storyPoints: visible(false),
    labels: visible(false),
    fixVersions: visible(false),
    dueDate: visible(false),
  },
  subtask: {
    title: visible(true),
    description: visible(false),
    project: visible(true),
    parent: visible(true), // required
    parentAllowedTypes: ["task", "bug"],
    sprint: visible(false),
    component: visible(false),
    assignee: visible(false),
    priority: visible(false),
    storyPoints: hidden,
    labels: visible(false),
    fixVersions: visible(false),
    dueDate: visible(false),
  },
};

export const TICKET_TYPE_LABEL: Record<TicketTypeV2, string> = {
  workpackage: "Workpackage",
  epic: "Epic",
  story: "Story",
  task: "Task",
  bug: "Bug",
  subtask: "Subtask",
};

export const TICKET_TYPE_BADGE: Record<TicketTypeV2, { letter: string; color: string }> = {
  workpackage: { letter: "W", color: "#6366f1" },
  epic: { letter: "E", color: "#a855f7" },
  story: { letter: "S", color: "#22c55e" },
  task: { letter: "T", color: "#3b82f6" },
  bug: { letter: "B", color: "#ef4444" },
  subtask: { letter: "s", color: "#94a3b8" },
};
