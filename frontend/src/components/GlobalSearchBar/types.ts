/**
 * A1b: Types for GlobalSearchBar and useTypeahead hook.
 */
import type { SearchItem } from "../../api/search";

export interface TypeaheadState {
  /** The current search query. */
  query: string;
  /** Direct-match result from the backend. Null or undefined when absent. */
  directMatch: SearchItem | null;
  /** Whether a fetch is in-flight. */
  isLoading: boolean;
  /** Error from the last fetch, if any. */
  error: string | null;
}
