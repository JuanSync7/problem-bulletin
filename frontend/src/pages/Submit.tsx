import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { useAnonymousMode } from "../hooks/useAnonymousMode";
import { useToast } from "../contexts/ToastContext";
import MarkdownEditor from "../components/MarkdownEditor";
import TagAutocomplete from "../components/TagAutocomplete";
import AttachmentDropZone from "../components/AttachmentDropZone";
import "./Submit.css";

interface Category {
  id: string;
  name: string;
}

interface Tag {
  id: string;
  name: string;
}

interface AttachmentFile {
  file: File;
  id: string;
}

interface FormErrors {
  title?: string;
  description?: string;
  category?: string;
}

function validateForm(
  title: string,
  description: string,
  categoryId: string
): FormErrors {
  const errors: FormErrors = {};

  if (!title.trim()) {
    errors.title = "Title is required";
  } else if (title.trim().length < 5) {
    errors.title = "Title must be at least 5 characters";
  } else if (title.trim().length > 200) {
    errors.title = "Title must be 200 characters or fewer";
  }

  if (!description.trim()) {
    errors.description = "Description is required";
  } else if (description.trim().length < 10) {
    errors.description = "Description must be at least 10 characters";
  }

  if (!categoryId) {
    errors.category = "Please select a category";
  }

  return errors;
}

export default function Submit() {
  const auth = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const { isAnonymous } = useAnonymousMode();

  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [categories, setCategories] = useState<Category[]>([]);
  const [domainId, setDomainId] = useState("");
  const [domains, setDomains] = useState<{ id: string; name: string }[]>([]);
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);
  const [attachments, setAttachments] = useState<AttachmentFile[]>([]);
  const [anonymous, setAnonymous] = useState(false);
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [touched, setTouched] = useState<Record<string, boolean>>({});

  // Fetch categories
  useEffect(() => {
    let cancelled = false;
    async function fetchCategories() {
      try {
        const res = await fetch("/api/admin/categories", {
          credentials: "include",
        });
        if (res.ok && !cancelled) {
          const data: Category[] = await res.json();
          setCategories(data);
        }
      } catch {
        // Categories will remain empty; user sees empty dropdown
      }
    }
    fetchCategories();
    async function fetchDomains() {
      try {
        const res = await fetch("/api/domains", { credentials: "include" });
        if (res.ok && !cancelled) {
          setDomains(await res.json());
        }
      } catch {
        // ignore
      }
    }
    fetchDomains();
    return () => {
      cancelled = true;
    };
  }, []);

  // Revalidate on field changes when fields have been touched
  useEffect(() => {
    if (Object.keys(touched).length > 0) {
      const newErrors = validateForm(title, description, categoryId);
      // Only show errors for touched fields
      const visibleErrors: FormErrors = {};
      if (touched.title && newErrors.title) visibleErrors.title = newErrors.title;
      if (touched.description && newErrors.description)
        visibleErrors.description = newErrors.description;
      if (touched.category && newErrors.category)
        visibleErrors.category = newErrors.category;
      setErrors(visibleErrors);
    }
  }, [title, description, categoryId, touched]);

  const markTouched = (field: string) => {
    setTouched((prev) => ({ ...prev, [field]: true }));
  };

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();

      // Mark all as touched
      setTouched({ title: true, description: true, category: true });

      const formErrors = validateForm(title, description, categoryId);
      if (Object.keys(formErrors).length > 0) {
        setErrors(formErrors);
        return;
      }

      setIsSubmitting(true);

      try {
        // 1. Create the problem
        const res = await fetch("/api/problems", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({
            title: title.trim(),
            description: description.trim(),
            category_id: categoryId,
            domain_id: domainId || null,
            tags: selectedTags.map((t) => t.id),
            is_anonymous: isAnonymous,
            anonymous,
          }),
        });

        if (!res.ok) {
          const body = await res
            .json()
            .catch(() => ({ message: "Failed to submit problem" }));
          throw new Error(body.message || "Failed to submit problem");
        }

        const problem = await res.json();

        // 2. Upload attachments one at a time (backend accepts single file)
        if (attachments.length > 0) {
          const failedFiles: string[] = [];
          for (const af of attachments) {
            const formData = new FormData();
            formData.append("file", af.file);
            try {
              const uploadRes = await fetch(
                `/api/problems/${problem.id}/attachments`,
                {
                  method: "POST",
                  credentials: "include",
                  body: formData,
                }
              );
              if (!uploadRes.ok) {
                failedFiles.push(af.file.name);
              }
            } catch {
              failedFiles.push(af.file.name);
            }
          }
          if (failedFiles.length > 0) {
            toast.show(
              `Problem created but failed to upload: ${failedFiles.join(", ")}`,
              "error"
            );
          }
        }

        toast.show("Problem submitted successfully!", "success");
        navigate(`/problems/${problem.id}`);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "Failed to submit problem";
        toast.show(message, "error");
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      title,
      description,
      categoryId,
      selectedTags,
      attachments,
      anonymous,
      navigate,
      toast,
    ]
  );

  // Loading state
  if (auth.isLoading) {
    return (
      <div className="submit-page">
        <div className="app-loading">
          <div className="app-loading__spinner" />
        </div>
      </div>
    );
  }

  // Not logged in
  if (!auth.isAuthenticated) {
    return (
      <div className="submit-page">
        <div className="submit-page__login">
          <p>You need to be logged in to submit a problem.</p>
          <button
            type="button"
            className="submit-page__login-btn"
            onClick={auth.login}
          >
            Sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="submit-page">
      <h1 className="submit-page__title">Submit a Problem</h1>

      <form className="submit-form" onSubmit={handleSubmit} noValidate>
        {/* Title */}
        <div className="form-field">
          <label className="form-field__label" htmlFor="submit-title">
            Title<span className="form-field__required">*</span>
          </label>
          <input
            id="submit-title"
            type="text"
            className={`form-field__input${
              errors.title ? " form-field__input--error" : ""
            }`}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => markTouched("title")}
            placeholder="Summarize the problem in a few words"
            maxLength={200}
            autoFocus
          />
          {errors.title && (
            <span className="form-field__error">{errors.title}</span>
          )}
          <span className="form-field__hint">{title.length} / 200</span>
        </div>

        {/* Description */}
        <div className="form-field">
          <label className="form-field__label">
            Description<span className="form-field__required">*</span>
          </label>
          <MarkdownEditor
            value={description}
            onChange={(val) => {
              setDescription(val);
              if (!touched.description) markTouched("description");
            }}
            placeholder="Describe the problem in detail. Markdown is supported."
            minLength={10}
          />
          {errors.description && (
            <span className="form-field__error">{errors.description}</span>
          )}
        </div>

        {/* Category */}
        <div className="form-field">
          <label className="form-field__label" htmlFor="submit-category">
            Category<span className="form-field__required">*</span>
          </label>
          <select
            id="submit-category"
            className="form-field__select"
            value={categoryId}
            onChange={(e) => setCategoryId(e.target.value)}
            onBlur={() => markTouched("category")}
          >
            <option value="">Select a category</option>
            {categories.map((cat) => (
              <option key={cat.id} value={cat.id}>
                {cat.name}
              </option>
            ))}
          </select>
          {errors.category && (
            <span className="form-field__error">{errors.category}</span>
          )}
        </div>

        {/* Domain */}
        <div className="form-field">
          <label className="form-field__label" htmlFor="submit-domain">
            Domain
          </label>
          <select
            id="submit-domain"
            className="form-field__select"
            value={domainId}
            onChange={(e) => setDomainId(e.target.value)}
          >
            <option value="">Select a domain (optional)</option>
            {domains.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </div>

        {/* Tags */}
        <div className="form-field">
          <label className="form-field__label">Tags</label>
          <TagAutocomplete
            selectedTags={selectedTags}
            onChange={setSelectedTags}
            maxTags={10}
          />
        </div>

        {/* Attachments */}
        <div className="form-field">
          <label className="form-field__label">Attachments</label>
          <AttachmentDropZone files={attachments} onChange={setAttachments} />
        </div>

        {/* Anonymous */}
        <div className="form-field">
          <div className="form-field__checkbox-wrap">
            <input
              type="checkbox"
              id="submit-anonymous"
              className="form-field__checkbox"
              checked={anonymous}
              onChange={(e) => setAnonymous(e.target.checked)}
            />
            <label
              htmlFor="submit-anonymous"
              className="form-field__checkbox-label"
            >
              Submit anonymously
            </label>
          </div>
        </div>

        {/* Actions */}
        <div className="submit-form__actions">
          <button
            type="submit"
            className="submit-form__btn"
            disabled={isSubmitting}
          >
            {isSubmitting && <span className="submit-form__spinner" />}
            {isSubmitting ? "Submitting..." : "Submit Problem"}
          </button>
        </div>
      </form>
    </div>
  );
}
