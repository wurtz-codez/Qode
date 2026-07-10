# Qode — Demo Video Script

**Total estimated runtime:** ~10–12 minutes
**Tone:** Enthusiastic, clear, developer-to-developer
**Preparation needed:**
- Have a `.zip` of a medium-sized project ready (e.g., a React app or Python library)
- Have a Gemini/OpenAI API key configured in the Settings panel beforehand
- Record at 1920×1080, browser window maximized

---

## Section 1: Opening Hook (0:00 – 0:30)

**On screen:** Browser showing `http://localhost:5173` — the landing page with the Qode logo, tagline, color-coded legend pills, and 6 feature cards.

**Script:**
> "Have you ever dropped into a new codebase and spent hours just trying to figure out where things live? What calls what? What breaks if you change something?
>
> Qode is a local-first code intelligence system that builds a high-fidelity knowledge graph of your code right here in the browser. Everything runs in WebAssembly — your code never leaves your machine.
>
> Let me show you how it works."

---

## Section 2: Landing Page Walkthrough (0:30 – 1:30)

**On screen:** Hover over the tagline "Understand Code at the Speed of Thought". Scroll down to the About section. Point to the legend pills (File, Folder, Class, Function, Interface, Method).

**Script:**
> "The landing page gives you a quick overview. These pills show the color-coded node types you'll see in the graph — Files in blue, Functions in emerald green, Classes in amber, and so on.
>
> Below are the six core capabilities: a visual graph explorer, AI-powered insights, semantic search, blast radius analysis, the folder structure browser, and method tracing.
>
> Qode supports 12 languages: JavaScript, TypeScript, Python, Java, Kotlin, C, C++, C#, Go, Rust, PHP, and Swift — all parsed using Tree-sitter ASTs running in WASM."

---

## Section 3: Loading a Codebase (1:30 – 2:30)

**On screen:** Click "Upload Project" → transitions to the DropZone. Show the three tabs: ZIP Upload, GitHub URL, Server.

**Script:**
> "Clicking 'Upload Project' takes us to the drop zone. You have three ways to load a codebase.
>
> Option one: drag and drop a ZIP file of any project. Option two: paste a GitHub URL — Qode uses isomorphic-git to do a shallow clone right in the browser. You can even add a personal access token for private repositories.
>
> Option three: connect to a pre-indexed Qode server if you have one running, which lets you switch between multiple repos.
>
> I'll use a ZIP file of a React project I prepared earlier."

**Action:** Drag a `.zip` file onto the dropzone.

---

## Section 4: The Indexing Pipeline (2:30 – 4:00)

**On screen:** Full-screen loading overlay with the pulsing gradient orb, progress bar, phase messages, and live stats (files processed, nodes created).

**Script:**
> "As soon as the file lands, Qode kicks off a 9-phase ingestion pipeline — all running inside a Web Worker so the UI stays responsive.
>
> Phase one: extracting the ZIP and loading file contents into memory.
>
> Phase two: walking the file tree and creating Folder and File nodes in the graph database — which is KuzuDB, an embedded columnar graph database compiled to WASM.
>
> Phase three: parsing every file with Tree-sitter WASM — extracting every function, class, method, interface, variable, and import across all 12 supported languages. You can watch it process each file in real time.
>
> Phase four: resolving imports between files — understanding the dependency graph.
>
> Phase five: tracing function calls across files.
>
> Phase six: extracting class inheritance hierarchies — extends and implements relationships.
>
> Phase seven: running the Leiden clustering algorithm to group related symbols into logical communities — this is what gives the graph its structure.
>
> Phase eight: detecting execution flows from entry points through call chains.
>
> And finally, phase nine: completion — with stats on communities, processes, and total nodes."

---

## Section 5: Graph Exploration — The Core Experience (4:00 – 5:30)

**On screen:** The main Exploring view. The graph is rendered with Sigma.js WebGL. Nodes are color-coded, edges show relationships. Background is dark.

**Script:**
> "And here we are — the main exploration view. This is a force-directed graph rendered with Sigma.js using WebGL, so it stays smooth even with thousands of nodes.
>
> Every node is color-coded: blue files, indigo folders, amber classes, green functions, pink interfaces. When a symbol belongs to a community, it takes on that community's color — you can see these colored clusters forming natural groupings in the codebase."

**Action:** Pan around the graph, zoom in/out using scroll wheel. Hover over a node to show the tooltip pill.

> "I can pan by dragging, zoom with the scroll wheel. Hovering over any node shows its name. Clicking a node selects it and opens the code inspector on the left."

**Action:** Click a Function node (emerald). The CodeReferencesPanel opens on the left showing the file with syntax highlighting and the function's line range highlighted.

> "The code inspector shows the complete file with the selected symbol's lines highlighted. This is powered by react-syntax-highlighter with a VS Code Dark Plus theme."

---

## Section 6: File Tree & Filters (5:30 – 6:15)

**On screen:** Click the FileTreePanel on the left sidebar. Show the Explorer tab with the project hierarchy. Then switch to the Filters tab.

**Script:**
> "The left sidebar has two tabs. The Explorer tab shows a traditional file tree — click any file and the graph smoothly animates to focus on it, and the code inspector opens to show its contents.
>
> The Filters tab is where you control what you see. You can toggle individual node types on and off — hide the imports to reduce clutter, or show only classes and interfaces to understand the type hierarchy.
>
> You can also filter by depth — set it to 2 hops from any selected node and the graph instantly dims everything outside that neighborhood. This is incredibly useful for focusing on a specific area of the codebase."

**Action:** Toggle off Import nodes, then toggle them back on. Click a file in the tree. Set depth filter to 2.

---

## Section 7: Search (6:15 – 6:45)

**On screen:** Press `⌘K` to focus the search bar in the header. Type a search term. Show results with type badges.

**Script:**
> "The global search bar — activated with Command-K — lets you find any node by name. Results show the node type badge so you can quickly tell classes from functions. Clicking a result focuses the graph camera on that node and selects it."

**Action:** Search for something like "handle" or "button" — click a result to focus the graph.

---

## Section 8: Cypher Querying (6:45 – 7:30)

**On screen:** Click the cyan "Query" FAB at the bottom-left. The Cypher query panel opens. Type a query and run it.

**Script:**
> "Under the hood, the knowledge graph lives in KuzuDB — a full SQL-powered graph database running in WebAssembly. You can query it directly using Cypher — the same query language used by Neo4j.
>
> Clicking this floating action button opens the Cypher panel. Let me run a simple query."

**Action:** Type `MATCH (n:Function)-[r:CALLS]->(m:Function) RETURN n.name, m.name LIMIT 20` and press ⌘+Enter.

> "This finds all function-to-function call relationships. The results appear in a table, and every referenced node gets highlighted in the graph. You can use the example queries to get started — Find All Functions, All Classes, Import Dependencies, and so on."

---

## Section 9: AI Chat — QodeAI (7:30 – 9:30)

**On screen:** Click the "QodeAI" button in the header. The RightPanel opens on the right with the chat interface.

**Script:**
> "Now for the most powerful feature — the AI agent. QodeAI is a LangGraph ReAct agent with access to 7 tools specifically designed for codebase analysis.
>
> I have my API key pre-configured in Settings. Qode supports six providers: OpenAI, Gemini, Anthropic, Azure OpenAI, Ollama, and OpenRouter — so you can use whichever LLM you prefer."

**Action:** Type "Explain the architecture of this project" and send it. Watch the streaming response — show the tool call cards expanding and collapsing, the streaming text, and the final markdown-rendered answer with code citations.

> "Let me ask it to explain the project architecture. Watch closely — you'll see the agent's reasoning process stream in real time.
>
> It starts by using the Overview tool to get a high-level codebase map — all the clusters, processes, and cross-community dependencies. Then it drills into specific files with the Read tool.
>
> Every claim is grounded with clickable citations — these `[[file.ts:10-25]]` badges link directly to the code. Clicking one opens the code inspector and animates a glow effect on the cited lines."

**Action:** Click one of the citation badges. Show the glow animation on the CodeReferencesPanel.

> "The agent can also generate Mermaid diagrams on the fly. Let me ask it to show me the data flow."

**Action:** Type "Show me the data flow as a diagram" — the Mermaid diagram renders inline.

> "The agent uses seven tools in total: semantic + keyword search, Cypher graph queries, regex grep across all files, file reading, a codebase overview, deep symbol exploration, and impact analysis — which we'll look at next."

---

## Section 10: Impact / Blast Radius Analysis (9:30 – 10:15)

**On screen:** Type "What breaks if I change the file App.tsx?" — show the response with blast radius visualization in the graph.

**Script:**
> "This is my favorite feature. Let me ask: what breaks if I change a core file?
>
> The impact tool traces dependencies up to 3 hops deep and returns every affected node. The graph lights up — nodes directly affected glow red, their dependents are highlighted, and everything else dims. You can see the exact relationship chain: this file imports this class, which is extended by this component, which is called by this function.
>
> This turns 'I wonder what this change affects' from a guess into a visual, traceable map."

---

## Section 11: Processes & Execution Flows (10:15 – 11:00)

**On screen:** Switch to the "Processes" tab in the RightPanel. Show the list of detected execution flows. Click one to open the Mermaid flowchart modal.

**Script:**
> "The Processes tab lists every execution flow that Qode detected during indexing — grouped into cross-community processes and intra-community processes.
>
> Clicking 'View' opens a full-screen Mermaid flowchart showing the entire call chain. You can zoom, pan, and click 'Highlight in Graph' to see each step light up in the graph. This makes it trivial to trace how data moves through your application."

**Action:** Click "View" on a process → show the ProcessFlowModal with a Mermaid diagram. Zoom in. Click "Highlight in Graph" → the process steps glow in the main graph.

---

## Section 12: Semantic Search & Embeddings (11:00 – 11:30)

**On screen:** Click the "Enable Semantic Search" button in the header (if not already enabled). Show the EmbeddingStatus badge transition to "Ready".

**Script:**
> "One last feature: semantic search. Qode uses HuggingFace's Transformers.js to run the `snowflake-arctic-embed-xs` model entirely in the browser — either on WebGPU for speed or WASM as a fallback.
>
> This powers the AI agent's hybrid search, which combines BM25 keyword matching with vector embeddings using reciprocal rank fusion. The result is search that understands concepts, not just keywords."

---

## Section 13: Wrap-Up (11:30 – 12:00)

**On screen:** Zoom out to show the full graph with everything visible. Slowly fade.

**Script:**
> "So to recap: Qode takes your codebase, parses it with Tree-sitter, stores it in KuzuDB, clusters it with Leiden, visualizes it with Sigma.js, and gives you an AI agent that understands the architecture deeply enough to answer questions, trace impact, and explain how things work.
>
> Everything runs locally in your browser. No uploads, no servers, no data leaving your machine.
>
> Try it yourself at qode.ai — link in the description. Thanks for watching!"

---

## Appendix: Tech Stack Callouts

If you want to verbally mention tech stack throughout the demo, here's a cheat sheet of where each technology appears:

| Tech | Where in demo |
|------|---------------|
| **React 18 + TypeScript** | Every UI component |
| **Sigma.js + Graphology** | Sections 5-6 (graph rendering) |
| **WebGL** | Section 5 (graph performance) |
| **Tree-sitter WASM** | Section 4 (parsing phase) |
| **KuzuDB WASM** | Sections 4, 8 (graph database + Cypher) |
| **Leiden clustering** | Section 4 (community detection phase) |
| **LangChain / LangGraph** | Sections 9-10 (AI agent orchestration) |
| **HuggingFace Transformers.js** | Section 12 (embeddings) |
| **Web Workers + Comlink** | Section 4 (non-blocking pipeline) |
| **Tailwind CSS v4** | Every UI element |
| **Mermaid** | Section 11 (execution flow diagrams) |
| **isomorphic-git** | Section 3 (GitHub clone) |
| **Vite** | Dev server / build |
