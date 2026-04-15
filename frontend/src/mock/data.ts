/**
 * Mock data for GitHub Pages demo mode.
 * When API calls fail (no backend), this data is used instead.
 */

const MOCK_USERS = [
  { id: "u1", display_name: "Alice Chen", email: "alice@aion.dev", role: "admin" },
  { id: "u2", display_name: "Bob Martinez", email: "bob@aion.dev", role: "member" },
  { id: "u3", display_name: "Carol Kim", email: "carol@aion.dev", role: "member" },
  { id: "u4", display_name: "Dave Patel", email: "dave@aion.dev", role: "member" },
];

const MOCK_CATEGORIES = [
  { id: "c1", name: "Engineering", slug: "engineering", sort_order: 0 },
  { id: "c2", name: "Infrastructure", slug: "infrastructure", sort_order: 1 },
  { id: "c3", name: "Process", slug: "process", sort_order: 2 },
  { id: "c4", name: "Tooling", slug: "tooling", sort_order: 3 },
  { id: "c5", name: "Documentation", slug: "documentation", sort_order: 4 },
];

const MOCK_DOMAINS = [
  { id: "d1", name: "Front-End Design", slug: "front-end-design", sort_order: 0 },
  { id: "d2", name: "DFT", slug: "dft", sort_order: 1 },
  { id: "d3", name: "Verification", slug: "verification", sort_order: 2 },
  { id: "d4", name: "Physical Design", slug: "physical-design", sort_order: 3 },
  { id: "d5", name: "Si-Ops", slug: "si-ops", sort_order: 4 },
  { id: "d6", name: "Architecture", slug: "architecture", sort_order: 5 },
];

const now = new Date();
const ago = (hours: number) => new Date(now.getTime() - hours * 3600000).toISOString();

export const MOCK_PROBLEMS = [
  {
    id: "p1",
    seq_number: 1,
    display_id: "AION-001",
    title: "Timing closure failure on critical path in ALU",
    description: "The ALU critical path is failing timing at 1.2GHz target. Setup slack is -0.15ns on the carry chain. We've tried retiming but the logic depth is fundamentally too deep.\n\n---\n\n**Impact:** Blocks tapeout schedule by 2 weeks if not resolved.\n\n**What we've tried:**\n- Gate sizing on carry chain\n- Retiming across pipeline stages\n- Alternative adder architectures (Kogge-Stone vs Brent-Kung)",
    status: "open",
    category: MOCK_CATEGORIES[0],
    domain: MOCK_DOMAINS[3],
    tags: [{ id: "t1", name: "timing" }, { id: "t2", name: "P0" }],
    upstar_count: 12,
    is_upstarred: false,
    is_claimed: false,
    claims: [],
    solution_count: 2,
    comment_count: 5,
    author: MOCK_USERS[0],
    created_at: ago(72),
    activity_at: ago(2),
  },
  {
    id: "p2",
    seq_number: 2,
    display_id: "AION-002",
    title: "DRC violations in metal fill around analog block",
    description: "Metal fill generation is producing DRC violations at the boundary of the analog block. The fill exclusion zone isn't being respected by the automated fill tool.\n\nSpecifically seeing M4/M5 density violations within 2um of the analog keep-out region.",
    status: "claimed",
    category: MOCK_CATEGORIES[3],
    domain: MOCK_DOMAINS[3],
    tags: [{ id: "t3", name: "DRC" }, { id: "t4", name: "analog" }],
    upstar_count: 8,
    is_upstarred: true,
    is_claimed: true,
    claims: [MOCK_USERS[2]],
    solution_count: 1,
    comment_count: 3,
    author: MOCK_USERS[1],
    created_at: ago(48),
    activity_at: ago(6),
  },
  {
    id: "p3",
    seq_number: 3,
    display_id: "AION-003",
    title: "Scan chain reorder causing coverage drop",
    description: "After the latest scan chain reorder for ATPG optimization, stuck-at coverage dropped from 98.2% to 94.7%. The reorder was supposed to improve pattern count but seems to have introduced hard-to-detect faults.\n\nNeed to analyze which faults became undetectable.",
    status: "open",
    category: MOCK_CATEGORIES[2],
    domain: MOCK_DOMAINS[1],
    tags: [{ id: "t5", name: "DFT" }, { id: "t6", name: "ATPG" }],
    upstar_count: 5,
    is_upstarred: false,
    is_claimed: false,
    claims: [],
    solution_count: 0,
    comment_count: 2,
    author: MOCK_USERS[2],
    created_at: ago(24),
    activity_at: ago(12),
  },
  {
    id: "p4",
    seq_number: 4,
    display_id: "AION-004",
    title: "UVM scoreboard mismatch on AXI burst transactions",
    description: "The AXI verification environment is showing scoreboard mismatches on WRAP burst type transactions when burst length > 4. INCR bursts work fine.\n\nSuspect the DUT is not wrapping the address correctly at the boundary.",
    status: "solved",
    category: MOCK_CATEGORIES[0],
    domain: MOCK_DOMAINS[2],
    tags: [{ id: "t7", name: "UVM" }, { id: "t8", name: "AXI" }],
    upstar_count: 15,
    is_upstarred: false,
    is_claimed: false,
    claims: [],
    solution_count: 3,
    comment_count: 8,
    author: MOCK_USERS[3],
    created_at: ago(120),
    activity_at: ago(1),
  },
  {
    id: "p5",
    seq_number: 5,
    display_id: "AION-005",
    title: "Power grid IR drop exceeding 5% target on core VDD",
    description: "IR drop analysis shows 7.2% drop in the southeast corner of the die, exceeding our 5% budget. The power mesh in this region was thinned to accommodate a large macro placement.\n\nNeed to evaluate options: reinforce mesh, add decaps, or re-floorplan.",
    status: "open",
    category: MOCK_CATEGORIES[1],
    domain: MOCK_DOMAINS[3],
    tags: [{ id: "t9", name: "power" }, { id: "t10", name: "IR-drop" }],
    upstar_count: 9,
    is_upstarred: false,
    is_claimed: false,
    claims: [],
    solution_count: 1,
    comment_count: 4,
    author: MOCK_USERS[0],
    created_at: ago(36),
    activity_at: ago(8),
  },
];

export const MOCK_SOLUTIONS: Record<string, any[]> = {
  p1: [
    {
      id: "s1",
      description: "Split the carry chain across two pipeline stages. This adds one cycle of latency but closes timing with +0.08ns margin. The downstream control logic needs minor updates to handle the extra pipeline stage.",
      upvote_count: 7,
      is_upvoted: false,
      version_count: 1,
      status: "under_review",
      author: MOCK_USERS[2],
      created_at: ago(48),
    },
    {
      id: "s2",
      description: "Use a hybrid Ling-adder architecture for the upper 32 bits. Benchmarked at 15% faster than Kogge-Stone with similar area. I've attached the RTL diff.",
      upvote_count: 3,
      is_upvoted: true,
      version_count: 2,
      status: "pending",
      author: MOCK_USERS[3],
      created_at: ago(24),
    },
  ],
  p2: [
    {
      id: "s3",
      description: "Updated the fill exclusion TCL script to add a 3um buffer around analog keep-out regions. DRC clean after re-running fill. PR attached with the script changes.",
      upvote_count: 5,
      is_upvoted: false,
      version_count: 1,
      status: "verified",
      author: MOCK_USERS[0],
      created_at: ago(24),
    },
  ],
  p4: [
    {
      id: "s4",
      description: "Fixed the address wrap calculation in the AXI slave module. The wrap boundary was being computed as `(burst_len * data_width)` but should be `(burst_len * strobe_width)`. All WRAP burst tests passing now.",
      upvote_count: 12,
      is_upvoted: false,
      version_count: 1,
      status: "accepted",
      author: MOCK_USERS[1],
      created_at: ago(96),
    },
  ],
  p5: [
    {
      id: "s5",
      description: "Added two additional M6/M7 power straps in the affected region and inserted a row of decap cells along the macro boundary. IR drop now at 4.3%.",
      upvote_count: 4,
      is_upvoted: false,
      version_count: 1,
      status: "pending",
      author: MOCK_USERS[3],
      created_at: ago(12),
    },
  ],
};

export const MOCK_COMMENTS: Record<string, any[]> = {
  p1: [
    {
      id: "cm1",
      body: "Have we considered using clock borrowing from the adjacent pipeline stage? There might be margin we can steal.",
      author: MOCK_USERS[1],
      is_edited: false,
      created_at: ago(60),
      replies: [
        {
          id: "cm2",
          body: "Clock borrowing is risky here because the adjacent stage is already at -0.02ns. We'd just be moving the problem.",
          author: MOCK_USERS[0],
          is_edited: false,
          created_at: ago(58),
          replies: [],
        },
        {
          id: "cm3",
          body: "Agreed with Alice. The whole pipeline is tight. I think the two-stage split is the right call.",
          author: MOCK_USERS[3],
          is_edited: false,
          created_at: ago(55),
          replies: [],
        },
      ],
    },
    {
      id: "cm4",
      body: "FYI — the architecture team confirmed one extra cycle latency is acceptable for this datapath.",
      author: MOCK_USERS[2],
      is_edited: false,
      created_at: ago(30),
      replies: [],
    },
  ],
  p4: [
    {
      id: "cm5",
      body: "Great catch! This was a subtle bug. The spec is actually ambiguous on this — section A3.4.1 uses 'size' in two different ways.",
      author: MOCK_USERS[0],
      is_edited: false,
      created_at: ago(90),
      replies: [
        {
          id: "cm6",
          body: "We should add a regression test specifically for WRAP bursts with all supported lengths. I'll add it to the UVM sequence library.",
          author: MOCK_USERS[3],
          is_edited: true,
          created_at: ago(85),
          replies: [],
        },
      ],
    },
  ],
};

export const MOCK_LEADERBOARD = {
  top_solvers: [
    { user_id: "u2", display_name: "Bob Martinez", accepted_count: 8 },
    { user_id: "u1", display_name: "Alice Chen", accepted_count: 6 },
    { user_id: "u4", display_name: "Dave Patel", accepted_count: 5 },
    { user_id: "u3", display_name: "Carol Kim", accepted_count: 3 },
  ],
  top_reporters: [
    { user_id: "u1", display_name: "Alice Chen", problem_count: 12 },
    { user_id: "u4", display_name: "Dave Patel", problem_count: 9 },
    { user_id: "u3", display_name: "Carol Kim", problem_count: 7 },
    { user_id: "u2", display_name: "Bob Martinez", problem_count: 4 },
  ],
};

export const MOCK_TAGS = (() => {
  const seen = new Map<string, { id: string; name: string; usage_count: number }>();
  for (const p of MOCK_PROBLEMS) {
    for (const tag of p.tags) {
      if (seen.has(tag.id)) {
        seen.get(tag.id)!.usage_count += 1;
      } else {
        seen.set(tag.id, { id: tag.id, name: tag.name, usage_count: 1 });
      }
    }
  }
  return Array.from(seen.values()).sort((a, b) => a.name.localeCompare(b.name));
})();

export { MOCK_USERS, MOCK_CATEGORIES, MOCK_DOMAINS };
