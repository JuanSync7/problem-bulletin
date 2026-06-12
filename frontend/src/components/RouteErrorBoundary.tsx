import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class RouteErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack?: string }) {
    // Surface to the browser console; do not swallow.
    // eslint-disable-next-line no-console
    console.error("RouteErrorBoundary caught:", error, info.componentStack);
  }

  handleReset = () => {
    this.setState({ error: null });
  };

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          style={{
            padding: "2rem",
            margin: "2rem auto",
            maxWidth: 720,
            border: "1px solid #c0392b",
            borderRadius: 8,
            background: "#fff",
            color: "#2c2018",
          }}
        >
          <h2 style={{ marginTop: 0 }}>Something went wrong on this page.</h2>
          <pre
            style={{
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "#f7f1e3",
              padding: "0.75rem",
              borderRadius: 4,
              fontSize: 13,
            }}
          >
            {this.state.error.message}
          </pre>
          <button
            type="button"
            onClick={this.handleReset}
            style={{
              marginTop: "0.75rem",
              padding: "0.4rem 0.9rem",
              borderRadius: 4,
              border: "1px solid #33322D",
              background: "#F7F5F0",
              cursor: "pointer",
            }}
          >
            Dismiss
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
