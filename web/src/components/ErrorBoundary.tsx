import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/** 捕获子树渲染异常，避免整页白屏。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="p-8 max-w-md mx-auto mt-16 text-center">
          <div className="text-4xl mb-3">💥</div>
          <h1 className="text-lg font-semibold text-ink mb-2">页面出错了</h1>
          <p className="text-xs text-ink-mute mb-4 font-mono break-all">
            {String(this.state.error?.message || this.state.error)}
          </p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 h-8 rounded-lg bg-accent text-white text-xs font-medium hover:bg-accent-hover"
          >
            刷新
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
