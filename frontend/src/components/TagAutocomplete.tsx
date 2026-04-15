import React, { useState, useRef, useEffect, useCallback } from "react";

interface Tag {
  id: string;
  name: string;
}

interface TagAutocompleteProps {
  selectedTags: Tag[];
  onChange: (tags: Tag[]) => void;
  maxTags?: number;
}

const MAX_TAGS_DEFAULT = 10;

export default function TagAutocomplete({
  selectedTags,
  onChange,
  maxTags = MAX_TAGS_DEFAULT,
}: TagAutocompleteProps) {
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<Tag[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [isLoading, setIsLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const fetchTags = useCallback(
    async (query: string) => {
      if (query.length < 2) {
        setSuggestions([]);
        setIsOpen(false);
        return;
      }

      setIsLoading(true);
      try {
        const res = await fetch(
          `/api/tags?q=${encodeURIComponent(query)}`,
          { credentials: "include" }
        );
        if (res.ok) {
          const data: Tag[] = await res.json();
          const filtered = data.filter(
            (t) => !selectedTags.some((s) => s.id === t.id)
          );
          setSuggestions(filtered);
          setIsOpen(filtered.length > 0);
          setActiveIndex(-1);
        }
      } catch {
        setSuggestions([]);
      } finally {
        setIsLoading(false);
      }
    },
    [selectedTags]
  );

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (input.length < 2) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }
    debounceRef.current = setTimeout(() => fetchTags(input), 200);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [input, fetchTags]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectTag = (tag: Tag) => {
    if (selectedTags.length >= maxTags) return;
    onChange([...selectedTags, tag]);
    setInput("");
    setSuggestions([]);
    setIsOpen(false);
    inputRef.current?.focus();
  };

  const removeTag = (tagId: string) => {
    onChange(selectedTags.filter((t) => t.id !== tagId));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (!isOpen || suggestions.length === 0) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setActiveIndex((prev) =>
          prev < suggestions.length - 1 ? prev + 1 : 0
        );
        break;
      case "ArrowUp":
        e.preventDefault();
        setActiveIndex((prev) =>
          prev > 0 ? prev - 1 : suggestions.length - 1
        );
        break;
      case "Enter":
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < suggestions.length) {
          selectTag(suggestions[activeIndex]);
        }
        break;
      case "Escape":
        setIsOpen(false);
        setActiveIndex(-1);
        break;
    }
  };

  const atMax = selectedTags.length >= maxTags;

  return (
    <div className="tag-autocomplete" ref={containerRef}>
      <div className="tag-autocomplete__input-wrap">
        <input
          ref={inputRef}
          type="text"
          className="tag-autocomplete__input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => {
            if (suggestions.length > 0) setIsOpen(true);
          }}
          placeholder={atMax ? `Max ${maxTags} tags` : "Search tags..."}
          disabled={atMax}
          aria-label="Search tags"
          aria-expanded={isOpen}
          role="combobox"
          aria-autocomplete="list"
        />
        {isLoading && <span className="tag-autocomplete__spinner" />}
      </div>

      {isOpen && suggestions.length > 0 && (
        <ul className="tag-autocomplete__dropdown" role="listbox">
          {suggestions.map((tag, i) => (
            <li
              key={tag.id}
              className={`tag-autocomplete__option${
                i === activeIndex ? " tag-autocomplete__option--active" : ""
              }`}
              role="option"
              aria-selected={i === activeIndex}
              onMouseDown={(e) => {
                e.preventDefault();
                selectTag(tag);
              }}
              onMouseEnter={() => setActiveIndex(i)}
            >
              {tag.name}
            </li>
          ))}
        </ul>
      )}

      {selectedTags.length > 0 && (
        <div className="tag-autocomplete__pills">
          {selectedTags.map((tag) => (
            <span key={tag.id} className="tag-autocomplete__pill">
              {tag.name}
              <button
                type="button"
                className="tag-autocomplete__pill-remove"
                onClick={() => removeTag(tag.id)}
                aria-label={`Remove tag ${tag.name}`}
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
