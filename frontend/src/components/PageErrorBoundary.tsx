import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

export class PageErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Compare page render failed", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <section className="panel" role="alert">
          <h2>แสดงผลการตรวจไม่สำเร็จ</h2>
          <p>ผลการตรวจยังไม่หายไป ลองโหลดหน้าเปรียบเทียบใหม่อีกครั้ง</p>
          <button className="primary" onClick={() => window.location.reload()}>
            โหลดหน้าใหม่
          </button>
        </section>
      );
    }
    return this.props.children;
  }
}
