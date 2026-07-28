import { useState } from 'react';
import { ScoreWorkspace } from './components/ScoreWorkspace/ScoreWorkspace';
import './App.css';

function App() {
  const [jobId, setJobId] = useState<string | null>(null);

  return (
    <section id="center">
      <div>
        <h1>TranscriScore</h1>
        <p>
          job_id를 입력하면 변환 상태와 악보 미리보기, 내보내기 버튼이 표시됩니다.
        </p>
      </div>

      <input
        type="text"
        placeholder="job_id (POST /upload 응답에서 확인, 또는 /docs에서 직접 업로드)"
        value={jobId ?? ''}
        onChange={(e) => setJobId(e.target.value.trim() || null)}
        style={{ width: '100%', maxWidth: 480, padding: '8px 12px', margin: '12px 0' }}
      />

      <ScoreWorkspace jobId={jobId} />
    </section>
  );
}

export default App;
