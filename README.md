# Qode

<div align="center">

  <h2>Building the nervous system for visual codebase exploration.</h2>

</div>

**Qode** indexes any codebase into a high-fidelity knowledge graph — mapping dependencies, execution flows, and architectures — giving you true structural awareness so you never miss critical context when exploring or modifying code.

> *Smarter than basic code search.* Traditional search just finds text. Qode lets you *analyze* the architecture — tracking relationships, dependencies, and complex data flows, directly in your browser.

**TL;DR:** The **Qode Web UI** offers a visual, interactive graph explorer and AI chat interface. It runs entirely in your browser using WebAssembly (WASM), allowing you to drop a zipped codebase into the app and instantly explore its complete architectural map without uploading your code to any external server.

*(Note: The CLI tooling for AI Agent integrations is currently undergoing maintenance and has been temporarily removed from this documentation. Please use the Web UI for codebase exploration.)*

---

## 🌟 What does it do?

Qode builds a complete knowledge graph of your codebase through a multi-phase indexing pipeline, entirely on the client side:

1. **Structure** — Walks the file tree and maps folder/file relationships.
2. **Parsing** — Extracts functions, classes, methods, and interfaces using Tree-sitter ASTs.
3. **Resolution** — Resolves imports and function calls across files with language-aware logic.
4. **Clustering** — Groups related symbols into functional communities.
5. **Processes** — Traces execution flows from entry points through call chains.
6. **Search** — Builds search indexes for fast retrieval and AI context.

### Supported Languages
TypeScript, JavaScript, Python, Java, Kotlin, C, C++, C#, Go, Rust, PHP, Swift

---

## 🚀 How to Use It

The project currently operates via a powerful, browser-based Web UI. No server installation is required — your code never leaves the browser.

### Running Locally

1. **Navigate to the web application folder:**
   ```bash
   cd qode-web
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Start the development server:**
   ```bash
   npm run dev
   ```

4. **Explore your code:**
   - Open [http://localhost:5173](http://localhost:5173) in your browser.
   - Drag & drop a `.zip` file of any supported codebase into the dropzone.
   - Qode will locally analyze, index, and render a rich 2D graph of your architecture!

---

## 🛠️ What is used in this project? (Tech Stack)

Qode achieves high-performance local indexing by leveraging WebAssembly and WebGL:

| Category            | Technology                                    |
| ------------------- | --------------------------------------------- |
| **Frontend**        | React 18, TypeScript, Vite, Tailwind v4       |
| **Visualization**   | Sigma.js + Graphology (WebGL)                 |
| **Parsing**         | Tree-sitter (WASM)                            |
| **Database**        | KuzuDB (WASM - Embedded graph database)       |
| **Embeddings/ML**   | HuggingFace transformers.js (WebGPU/WASM)     |
| **Agent Interface** | LangChain ReAct agent                         |
| **Clustering**      | Graphology (Louvain/Leiden algorithms)        |
| **Concurrency**     | Web Workers + Comlink (for non-blocking UI)   |

---

## 🔒 Security & Privacy

- **Everything runs in your browser.** No code is uploaded to any server.
- File parsing, graph creation, and search indexing happen entirely locally via WebAssembly.
- API keys (if provided for the AI chat) are stored securely in your browser's local storage only.
