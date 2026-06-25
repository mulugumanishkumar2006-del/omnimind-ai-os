// API Base Prefix
const API_PREFIX = "/api/v1";

// Cache for Chart instances to destroy them before redrawing
const charts = {};

// Active tab variable
let activeTab = "memories";

// Global analytics storage for cost/latency readouts
let globalStats = { latency: "0.00s", savings: "$0.00" };

// Document load initialization
document.addEventListener("DOMContentLoaded", () => {
    switchTab("memories");
    updateGlobalHeaderStats();
    // Refresh stats every 15 seconds
    setInterval(updateGlobalHeaderStats, 15000);
});

// Switch view panels
function switchTab(tabName) {
    activeTab = tabName;
    
    // Toggle active panel classes
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    document.querySelectorAll(".menu-item").forEach(b => b.classList.remove("active"));
    
    const targetPanel = document.getElementById(`panel-${tabName}`);
    const targetBtn = document.getElementById(`tab-btn-${tabName}`);
    
    if (targetPanel && targetBtn) {
        targetPanel.classList.add("active");
        targetBtn.classList.add("active");
    }
    
    // Update Workspace Title
    const titleMap = {
        memories: "Memory Vault",
        tasks: "Task Intelligence Workspace",
        knowledge: "Knowledge Graph Discovery",
        agents: "Multi-Agent System Collaboration",
        prompts: "Prompt Studio Workbench",
        search: "Intelligent Hybrid Search",
        meetings: "Meeting Intelligence Assistant",
        learning: "Learning Hub & Career Tracking",
        router: "Dynamic Model Router",
        security: "Security Center Auditor",
        improvement: "Self-Improvement Loop Engine",
        analytics: "AI Operations Monitoring Center"
    };
    document.getElementById("workspace-title").innerText = titleMap[tabName] || "Workspace";
    
    // Trigger tab-specific load actions
    initTabContent(tabName);
}

// Fetch helper wrappers
async function apiGet(endpoint) {
    try {
        const response = await fetch(`${API_PREFIX}${endpoint}`);
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.error("API GET Error:", e);
    }
    return null;
}

async function apiPost(endpoint, payload) {
    try {
        const response = await fetch(`${API_PREFIX}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.error("API POST Error:", e);
    }
    return null;
}

// Trigger loading logic depending on which panel is active
function initTabContent(tab) {
    if (tab === "memories") {
        loadMemoryTimeline();
    } else if (tab === "tasks") {
        loadTasksTree();
    } else if (tab === "knowledge") {
        loadKnowledgeGraph();
    } else if (tab === "agents") {
        loadAgentSessions();
    } else if (tab === "prompts") {
        loadPromptStudio();
    } else if (tab === "meetings") {
        loadMeetingsList();
    } else if (tab === "learning") {
        loadLearningHub();
    } else if (tab === "router") {
        loadRouterMetrics();
    } else if (tab === "security") {
        loadSecurityThreats();
    } else if (tab === "improvement") {
        loadImprovementLogs();
    } else if (tab === "analytics") {
        loadAnalyticsCenter();
    }
}

// Global Header Stats updater
async function updateGlobalHeaderStats() {
    const data = await apiGet("/analytics/dashboard");
    if (data) {
        document.getElementById("header-latency").innerText = `${data.avg_latency}s`;
        document.getElementById("header-savings").innerText = `$${(data.total_cost * 1.5).toFixed(4)}`;
    }
}

// ==================== 1. MEMORY VAULT ====================
async function loadMemoryTimeline() {
    const feed = document.getElementById("memory-timeline-feed");
    feed.innerHTML = "<div class='loading-placeholder'>Loading memories...</div>";
    
    const memories = await apiGet("/memories/");
    if (!memories || memories.length === 0) {
        feed.innerHTML = "<div class='loading-placeholder'>No memories stored yet. Record one below!</div>";
        return;
    }
    
    feed.innerHTML = "";
    memories.forEach(m => {
        const dt = new Date(m.created_at).toLocaleString();
        const card = document.createElement("div");
        card.className = "timeline-card";
        card.innerHTML = `
            <div style="font-weight:600; font-size:1.05rem; display:flex; justify-content:space-between; margin-bottom:0.4rem;">
                <span>Memory Entry [${m.type.replace('_',' ').toUpperCase()}]</span>
                <span style="color:#3b82f6;">Importance: ${m.importance_score.toFixed(1)}/10</span>
            </div>
            <p style="color:#d1d5db; line-height:1.4;">${m.content}</p>
            <div class="timeline-card-header">
                <span>Logged: ${dt}</span>
                <button class="btn-delete" style="background:none; border:none; color:#ef4444; cursor:pointer;" onclick="deleteMemory('${m.id}')">Delete</button>
            </div>
        `;
        feed.appendChild(card);
    });
}

async function recordMemory() {
    const type = document.getElementById("input-memory-type").value;
    const content = document.getElementById("input-memory-content").value;
    
    if (!content) return;
    
    const res = await apiPost("/memories/", { content, type });
    if (res) {
        document.getElementById("input-memory-content").value = "";
        loadMemoryTimeline();
        updateGlobalHeaderStats();
    }
}

async function deleteMemory(id) {
    const res = await fetch(`${API_PREFIX}/memories/${id}`, { method: "DELETE" });
    if (res.ok) {
        loadMemoryTimeline();
    }
}

// ==================== 2. TASK WORKSPACE ====================
async function loadTasksTree() {
    const container = document.getElementById("tasks-tree-container");
    container.innerHTML = "<div class='loading-placeholder'>Loading tasks...</div>";
    
    const tasks = await apiGet("/tasks/");
    if (!tasks || tasks.length === 0) {
        container.innerHTML = "<div class='loading-placeholder'>No active goals found. Set a goal to get started!</div>";
        return;
    }
    
    container.innerHTML = "";
    tasks.forEach(t => {
        const item = document.createElement("div");
        item.className = "task-tree-item";
        
        let bd_button = "";
        if (t.type === "goal" && (!t.subtasks || t.subtasks.length === 0)) {
            bd_button = `<button class="btn-primary" style="padding:0.4rem 0.8rem; font-size:0.8rem; width:auto; margin-top:0.5rem;" onclick="breakdownGoal('${t.id}')">AI Subtask Breakdown</button>`;
        }
        
        item.innerHTML = `
            <div class="task-tree-row">
                <div>
                    <strong>${t.title}</strong>
                    <div style="font-size:0.8rem; color:#9ca3af; margin-top:0.2rem;">${t.description || "No description"}</div>
                </div>
                <div style="text-align:right;">
                    <span class="badge badge-${t.status}">${t.status.replace('_',' ')}</span>
                    <div class="progress-bar-wrap">
                        <div class="progress-bar-fill" style="width: ${t.progress}%"></div>
                    </div>
                    <span style="font-size:0.75rem; color:#9ca3af;">Progress: ${t.progress}%</span>
                </div>
            </div>
            ${bd_button}
        `;
        
        if (t.subtasks && t.subtasks.length > 0) {
            const subContainer = document.createElement("div");
            subContainer.className = "task-subtasks-container";
            
            t.subtasks.forEach(sub => {
                const subRow = document.createElement("div");
                subRow.style.display = "flex";
                subRow.style.justify = "space-between";
                subRow.style.marginBottom = "0.5rem";
                
                let check_btn = "";
                if (sub.status !== "completed") {
                    check_btn = `<button style="background:none; border:none; color:#10b981; cursor:pointer; font-weight:600; font-size:0.8rem;" onclick="completeSubtask('${sub.id}')">✓ Mark Done</button>`;
                }
                
                subRow.innerHTML = `
                    <span>• <b>${sub.title}</b> [${sub.status.replace('_',' ')}]</span>
                    <span>${check_btn}</span>
                `;
                subContainer.appendChild(subRow);
            });
            item.appendChild(subContainer);
        }
        
        container.appendChild(item);
    });
}

async function createGoal() {
    const title = document.getElementById("input-goal-title").value;
    const description = document.getElementById("input-goal-desc").value;
    const type = document.getElementById("input-goal-type").value;
    const estimated_hours = parseFloat(document.getElementById("input-goal-estimate").value);
    
    if (!title) return;
    
    const res = await apiPost("/tasks/", { title, description, type, estimated_hours });
    if (res) {
        document.getElementById("input-goal-title").value = "";
        document.getElementById("input-goal-desc").value = "";
        loadTasksTree();
    }
}

async function breakdownGoal(id) {
    const container = document.getElementById("tasks-tree-container");
    container.innerHTML = "<div class='loading-placeholder'>Generating subtasks roadmap...</div>";
    
    const res = await apiPost(`/tasks/${id}/breakdown`, {});
    if (res) {
        loadTasksTree();
    }
}

async function completeSubtask(id) {
    const response = await fetch(`${API_PREFIX}/tasks/${id}/progress?progress=100.0&status=completed`, {
        method: "PUT"
    });
    if (response.ok) {
        loadTasksTree();
    }
}

// ==================== 3. KNOWLEDGE GRAPH ====================
async function loadKnowledgeGraph() {
    const canvas = document.getElementById("kg-network-canvas");
    canvas.innerHTML = "<div class='loading-placeholder'>Initializing graph database nodes...</div>";
    
    const data = await apiGet("/knowledge/graph");
    if (!data || data.nodes.length === 0) {
        canvas.innerHTML = "<div class='loading-placeholder'>Knowledge graph is empty. Insert data in the form below!</div>";
        return;
    }
    
    canvas.innerHTML = "";
    
    // Group categories and define node colors
    const colors = {
        language: "#fbbf24",      // yellow
        library: "#34d399",       // green
        database: "#f87171",      // red
        project: "#60a5fa",       // blue
        concept: "#c084fc",       // purple
        default: "#9ca3af"
    };
    
    const visNodes = data.nodes.map(n => {
        const type = n.type.toLowerCase();
        const color = colors[type] || colors.default;
        return {
            id: n.id,
            label: n.label,
            color: {
                background: color,
                border: "#111318",
                highlight: { background: "#ffffff", border: "#3b82f6" }
            },
            font: { color: "#ffffff" },
            shape: "dot",
            size: 20
        };
    });
    
    const visEdges = data.edges.map(e => {
        return {
            from: e.source,
            to: e.target,
            label: e.relation,
            arrows: "to",
            color: { color: "rgba(255,255,255,0.15)", highlight: "#3b82f6" },
            font: { color: "#9ca3af", size: 10 }
        };
    });
    
    const visData = { nodes: new vis.DataSet(visNodes), edges: new vis.DataSet(visEdges) };
    const options = {
        nodes: { borderWidth: 2 },
        physics: { barnesHut: { gravitationalConstant: -3000, centralGravity: 0.3 } }
    };
    
    new vis.Network(canvas, visData, options);
}

async function extractKnowledge() {
    const content = document.getElementById("input-kg-text").value;
    if (!content) return;
    
    const res = await apiPost("/knowledge/extract", { content });
    if (res) {
        document.getElementById("input-kg-text").value = "";
        const outcome = document.getElementById("kg-extraction-results");
        outcome.innerHTML = `
            <div style="background:rgba(16,185,129,0.05); color:#10b981; border:1px solid rgba(16,185,129,0.2); padding:0.8rem; border-radius:6px;">
                Extracted: ${res.nodes.length} Nodes, ${res.edges.length} Connections successfully mapped.
            </div>
        `;
        loadKnowledgeGraph();
    }
}

// ==================== 4. MULTI-AGENT COLLABORATION ====================
async function loadAgentSessions() {
    const container = document.getElementById("agents-history-container");
    container.innerHTML = "<div class='loading-placeholder'>Loading sessions...</div>";
    
    const sessions = await apiGet("/agents/sessions");
    if (!sessions || sessions.length === 0) {
        container.innerHTML = "<div class='loading-placeholder'>No agent collaborations executed yet. Assign a goal above!</div>";
        return;
    }
    
    container.innerHTML = "";
    sessions.forEach(s => {
        const item = document.createElement("div");
        item.className = "task-tree-item";
        item.innerHTML = `
            <div>
                <strong>Goal: "${s.goal}"</strong>
                <div style="font-size:0.8rem; color:#9ca3af; margin-top:0.3rem;">Status: <span style="color:#10b981;">${s.status.toUpperCase()}</span> | Steps: ${s.steps.length}</div>
            </div>
        `;
        container.appendChild(item);
    });
}

async function orchestrateAgents() {
    const goal = document.getElementById("input-agent-goal").value;
    if (!goal) return;
    
    const stepperPanel = document.getElementById("agent-stepper-panel");
    const feed = document.getElementById("agent-pipeline-feed");
    
    stepperPanel.style.display = "block";
    feed.innerHTML = "<div class='loading-placeholder'>Coordinator agent mapping out steps...</div>";
    
    const res = await apiPost("/agents/run", { goal });
    if (res) {
        feed.innerHTML = "";
        res.steps.forEach((step, idx) => {
            const card = document.createElement("div");
            card.className = "step-card";
            card.innerHTML = `
                <div class="step-card-header">
                    <strong>[${idx+1}] ${step.agent_name}</strong>
                    <span style="color:#6b7280;">${step.action} (${step.latency.toFixed(2)}s)</span>
                </div>
                <p style="font-size:0.9rem; color:#d1d5db; line-height:1.4;">${step.message}</p>
            `;
            feed.appendChild(card);
        });
        
        document.getElementById("agent-pipeline-status").innerText = "Pipeline Completed!";
        document.getElementById("input-agent-goal").value = "";
        loadAgentSessions();
        updateGlobalHeaderStats();
    }
}

// ==================== 5. PROMPT STUDIO ====================
async function loadPromptStudio() {
    const list = await apiGet("/prompts/");
    const select = document.getElementById("select-prompt-variants");
    
    if (list) {
        // Unique names
        const names = [...new Set(list.map(p => p.name))];
        select.innerHTML = '<option value="">-- Choose Prompt --</option>';
        names.forEach(name => {
            select.innerHTML += `<option value="${name}">${name}</option>`;
        });
    }
}

async function loadPromptVersions(name) {
    const list = await apiGet("/prompts/");
    const valA = document.getElementById("select-variant-a");
    const valB = document.getElementById("select-variant-b");
    
    valA.innerHTML = "";
    valB.innerHTML = "";
    
    if (!name || !list) return;
    
    const filtered = list.filter(p => p.name === name);
    filtered.forEach(p => {
        const optionText = `v${p.version} (${p.created_at.substring(5,16).replace('T', ' ')})`;
        valA.innerHTML += `<option value="${p.id}">${optionText}</option>`;
        valB.innerHTML += `<option value="${p.id}">${optionText}</option>`;
    });
}

async function registerPrompt() {
    const name = document.getElementById("input-prompt-name").value;
    const template = document.getElementById("input-prompt-template").value;
    
    if (!name || !template) return;
    
    const res = await apiPost("/prompts/", { name, template });
    if (res) {
        document.getElementById("input-prompt-name").value = "";
        document.getElementById("input-prompt-template").value = "";
        loadPromptStudio();
    }
}

async function runABTest() {
    const prompt_a_id = document.getElementById("select-variant-a").value;
    const prompt_b_id = document.getElementById("select-variant-b").value;
    const test_input = document.getElementById("input-compare-query").value;
    
    if (!prompt_a_id || !prompt_b_id || !test_input) return;
    
    const results = document.getElementById("ab-comparison-results");
    results.innerHTML = "<div class='loading-placeholder'>Simulating model executions side-by-side...</div>";
    
    const res = await apiPost("/prompts/compare", { prompt_a_id, prompt_b_id, test_input });
    if (res) {
        results.innerHTML = `
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:1rem; margin-top:1rem;">
                <div style="background:rgba(255,255,255,0.01); border:1px solid var(--border); padding:1rem; border-radius:6px;">
                    <strong>Variant A (v${res.prompt_a.version})</strong>
                    <div style="font-size:0.8rem; color:#9ca3af; margin:0.3rem 0;">Cost: $${res.prompt_a.cost.toFixed(6)} | Speed: ${res.prompt_a.latency.toFixed(2)}s</div>
                    <p style="font-size:0.9rem; color:#d1d5db;">${res.prompt_a.output}</p>
                </div>
                <div style="background:rgba(255,255,255,0.01); border:1px solid var(--border); padding:1rem; border-radius:6px;">
                    <strong>Variant B (v${res.prompt_b.version})</strong>
                    <div style="font-size:0.8rem; color:#9ca3af; margin:0.3rem 0;">Cost: $${res.prompt_b.cost.toFixed(6)} | Speed: ${res.prompt_b.latency.toFixed(2)}s</div>
                    <p style="font-size:0.9rem; color:#d1d5db;">${res.prompt_b.output}</p>
                </div>
            </div>
        `;
    }
}

// ==================== 6. HYBRID SEARCH ====================
async function executeSearch() {
    const query = document.getElementById("input-search-query").value;
    const filter = document.getElementById("select-search-filter").value;
    
    if (!query) return;
    
    const resultsFeed = document.getElementById("search-results-feed");
    const citationsFeed = document.getElementById("citations-feed");
    const citationsPanel = document.getElementById("citations-panel-container");
    
    resultsFeed.innerHTML = "<div class='loading-placeholder'>Searching workspace models...</div>";
    citationsPanel.style.display = "none";
    
    const res = await apiPost("/search/", { query, collection_filter: filter || null });
    if (res) {
        // Citations
        if (res.citations && res.citations.length > 0) {
            citationsPanel.style.display = "block";
            citationsFeed.innerHTML = "";
            res.citations.forEach(c => {
                citationsFeed.innerHTML += `
                    <div style="margin-bottom:0.5rem; font-size:0.85rem;">
                        📖 <b>${c.title}</b> (Confidence: ${(c.confidence*100).toFixed(0)}%) — <i>"${c.text_snippet}"</i>
                    </div>
                `;
            });
        }
        
        // Search results
        resultsFeed.innerHTML = "";
        res.results.forEach(r => {
            const card = document.createElement("div");
            card.className = "timeline-card";
            card.innerHTML = `
                <strong>${r.type.toUpperCase()}: ${r.title}</strong>
                <p style="color:#d1d5db; font-size:0.9rem; margin-top:0.4rem;">${r.content}</p>
            `;
            resultsFeed.appendChild(card);
        });
    }
}

// ==================== 7. MEETING INTELLIGENCE ====================
async function loadMeetingsList() {
    const container = document.getElementById("meetings-list-container");
    container.innerHTML = "<div class='loading-placeholder'>Loading meetings...</div>";
    
    const list = await apiGet("/meetings/");
    if (!list || list.length === 0) {
        container.innerHTML = "<div class='loading-placeholder'>No meeting summaries recorded.</div>";
        return;
    }
    
    container.innerHTML = "";
    list.forEach(m => {
        const card = document.createElement("div");
        card.className = "timeline-card";
        card.innerHTML = `
            <strong>📁 ${m.title}</strong>
            <p style="font-size:0.85rem; color:#d1d5db; margin:0.4rem 0;">${m.summary}</p>
            <div style="font-size:0.75rem; color:#9ca3af;">Decisions: ${m.decisions.join(", ")}</div>
        `;
        container.appendChild(card);
    });
}

async function processMeeting() {
    const title = document.getElementById("input-meeting-title").value;
    const transcript = document.getElementById("input-meeting-transcript").value;
    
    if (!title || !transcript) return;
    
    const outcome = document.getElementById("meeting-processing-outcome");
    outcome.innerHTML = "<div class='loading-placeholder'>Analyzing dialogue loops...</div>";
    
    const res = await apiPost("/meetings/process", { title, transcript });
    if (res) {
        outcome.innerHTML = `
            <div style="background:rgba(59,130,246,0.05); border:1px solid rgba(59,130,246,0.2); padding:1rem; border-radius:6px;">
                <strong>Analysis complete:</strong>
                <p style="font-size:0.9rem; margin:0.4rem 0;">${res.summary}</p>
                <div style="font-size:0.8rem; color:#3b82f6;">Tasks generated: ${res.action_items.length} action items.</div>
            </div>
        `;
        loadMeetingsList();
        updateGlobalHeaderStats();
    }
}

// ==================== 8. LEARNING HUB ====================
async function loadLearningHub() {
    const recommendationsPanel = document.getElementById("learning-recommendations-panel");
    recommendationsPanel.innerHTML = "<div class='loading-placeholder'>Evaluating skill indices...</div>";
    
    const skills = await apiGet("/learning/skills");
    
    // Draw competence bar chart
    if (skills && skills.length > 0) {
        const labels = skills.map(s => s.skill_name);
        const data = skills.map(s => s.progress);
        
        if (charts.skills) charts.skills.destroy();
        
        const ctx = document.getElementById("chart-skills-bar").getContext("2d");
        charts.skills = new Chart(ctx, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Acquisition %",
                    data,
                    backgroundColor: "#3b82f6",
                    borderRadius: 4
                }]
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { max: 100, grid: { color: "rgba(255,255,255,0.05)" } },
                    y: { grid: { display: false } }
                }
            }
        });
    }
    
    // Load recommendations
    const rec = await apiGet("/learning/career");
    if (rec) {
        recommendationsPanel.innerHTML = `
            <h4>Career Path Suggestion:</h4>
            <h3 style="color:#3b82f6; margin:0.3rem 0;">${rec.recommended_path}</h3>
            <p style="font-size:0.85rem; color:#9ca3af; margin-bottom:1rem;">Target duration: ${rec.timeline_months} months</p>
            <p style="font-size:0.9rem; line-height:1.4; margin-bottom:1rem;">${rec.rationale}</p>
            
            <strong>Gaps Detected:</strong>
            <div id="skills-gaps-list" style="margin-top:0.5rem; display:flex; flex-direction:column; gap:0.5rem;"></div>
        `;
        
        const gapsList = document.getElementById("skills-gaps-list");
        rec.required_skills.forEach(skill => {
            const row = document.createElement("div");
            row.style.display = "flex";
            row.style.justifyContent = "space-between";
            row.style.alignItems = "center";
            row.innerHTML = `
                <span>• ${skill}</span>
                <button class="btn-primary" style="width:auto; padding:0.3rem 0.6rem; font-size:0.75rem;" onclick="generateRoadmap('${skill}')">Acquire Roadmap</button>
            `;
            gapsList.appendChild(row);
        });
    }
}

async function addSkill() {
    const skill_name = document.getElementById("input-skill-name").value;
    const level = document.getElementById("select-skill-level").value;
    const progress = parseFloat(document.getElementById("input-skill-progress").value);
    const status = document.getElementById("select-skill-status").value;
    
    if (!skill_name) return;
    
    const res = await apiPost("/learning/skills", { skill_name, level, progress, status });
    if (res) {
        document.getElementById("input-skill-name").value = "";
        loadLearningHub();
    }
}

async function generateRoadmap(skillName) {
    const res = await apiPost(`/learning/roadmap?skill_name=${skillName}`, {});
    if (res) {
        alert(`Learning Roadmap for ${skillName} created under Task Intelligence!`);
        loadLearningHub();
    }
}

// ==================== 9. MODEL ROUTER ====================
async function loadRouterMetrics() {
    const logs = await apiGet("/router/logs");
    const tbody = document.querySelector("#table-router-logs tbody");
    
    tbody.innerHTML = "";
    
    if (!logs || logs.length === 0) {
        tbody.innerHTML = "<tr><td colspan='5' style='text-align:center;'>No routes logged.</td></tr>";
        return;
    }
    
    // Provider counts
    const providers = {};
    let totalCost = 0;
    
    logs.forEach(l => {
        providers[l.provider] = (providers[l.provider] || 0) + 1;
        totalCost += l.cost;
        
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${new Date(l.created_at).toLocaleTimeString()}</td>
            <td>${l.prompt_name}</td>
            <td>${l.model_name}</td>
            <td>$${l.cost.toFixed(6)}</td>
            <td>${l.latency.toFixed(2)}s</td>
        `;
        tbody.appendChild(tr);
    });
    
    // Draw chart allocations
    const labels = Object.keys(providers);
    const data = Object.values(providers);
    
    if (charts.router) charts.router.destroy();
    
    const ctx = document.getElementById("chart-router-allocations").getContext("2d");
    charts.router = new Chart(ctx, {
        type: "pie",
        data: {
            labels,
            datasets: [{
                data,
                backgroundColor: ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#9ca3af"]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { position: "right", labels: { color: "#ffffff" } } }
        }
    });
    
    // Routing stats readout
    const read = document.getElementById("router-stats-readout");
    const saving = totalCost * 1.5;
    read.innerHTML = `
        <h3>Allocations Auditor</h3>
        <p style="font-size:0.9rem; color:#9ca3af; margin:0.5rem 0;">System routed: <strong>${logs.length} calls</strong></p>
        <p style="font-size:0.9rem; color:#9ca3af; margin:0.5rem 0;">Accumulated Route Cost: <strong style="color:#ffffff;">$${totalCost.toFixed(5)}</strong></p>
        <p style="font-size:0.9rem; color:#9ca3af; margin:0.5rem 0;">Router Cost Savings: <strong style="color:#10b981;">$${saving.toFixed(5)}</strong></p>
    `;
}

// ==================== 10. SECURITY CENTER ====================
async function loadSecurityThreats() {
    const feed = document.getElementById("security-threats-feed");
    feed.innerHTML = "<div class='loading-placeholder'>Loading safety audits...</div>";
    
    const logs = await apiGet("/security/logs");
    if (!logs || logs.length === 0) {
        feed.innerHTML = "<div class='loading-placeholder'>Security audit history clean. No threats detected.</div>";
        return;
    }
    
    feed.innerHTML = "";
    logs.forEach(l => {
        const dt = new Date(l.created_at).toLocaleString();
        const card = document.createElement("div");
        card.style.background = "rgba(239, 68, 68, 0.02)";
        card.style.border = "1px solid rgba(239, 68, 68, 0.15)";
        card.style.borderLeft = "4px solid #ef4444";
        card.style.borderRadius = "8px";
        card.style.padding = "1rem";
        card.style.marginBottom = "1rem";
        card.innerHTML = `
            <div style="display:flex; justify-content:space-between; font-size:0.85rem; font-weight:600; color:#ef4444; margin-bottom:0.4rem;">
                <span>VULNERABILITY THREAT: ${l.scan_type.toUpperCase()}</span>
                <span>RISK LEVEL: ${l.risk_level.toUpperCase()} (Score: ${l.safety_score}%)</span>
            </div>
            <p style="font-size:0.9rem; color:#d1d5db;">Payload: <i>"${l.input_text}"</i></p>
            <div style="font-size:0.8rem; color:#ef4444; margin-top:0.4rem;">Triggers: ${l.threats_detected.join(", ")}</div>
            <div style="font-size:0.75rem; color:#9ca3af; margin-top:0.4rem;">Logged: ${dt}</div>
        `;
        feed.appendChild(card);
    });
}

async function scanInput() {
    const input_text = document.getElementById("input-security-text").value;
    if (!input_text) return;
    
    const results = document.getElementById("security-scan-results");
    results.innerHTML = "<div class='loading-placeholder'>Executing vulnerability scanner...</div>";
    
    const res = await apiPost("/security/scan", { input_text });
    if (res) {
        const statusClass = res.is_safe ? "success" : "danger";
        const statusText = res.is_safe ? "Clean Query" : "VULNERABILITY THREAT";
        results.innerHTML = `
            <div style="background:rgba(255,255,255,0.01); border:1px solid var(--border); padding:1rem; border-radius:6px; border-left:4px solid var(--${statusClass});">
                <div style="display:flex; justify-content:space-between;">
                    <strong>Scanner Status: <span style="color:var(--${statusClass});">${statusText}</span></strong>
                    <span>Safety Score: ${res.safety_score}%</span>
                </div>
                ${!res.is_safe ? `<p style="color:#ef4444; font-size:0.85rem; margin-top:0.3rem;">Flagged: ${res.threats.join(", ")}</p>` : ""}
            </div>
        `;
        document.getElementById("input-security-text").value = "";
        loadSecurityThreats();
    }
}

// ==================== 11. SELF-IMPROVEMENT ====================
async function loadImprovementLogs() {
    const feed = document.getElementById("improvement-logs-feed");
    feed.innerHTML = "<div class='loading-placeholder'>Loading optimization logs...</div>";
    
    const logs = await apiGet("/improvement/logs");
    if (!logs || logs.length === 0) {
        feed.innerHTML = "<div class='loading-placeholder'>No failed cases logged. Record a simulation case to inspect.</div>";
        return;
    }
    
    feed.innerHTML = "";
    logs.forEach(l => {
        const dt = new Date(l.created_at).toLocaleString();
        
        let opt_section = "";
        if (!l.optimized_prompt_id) {
            opt_section = `<button class="btn-primary" style="width:auto; padding:0.3rem 0.6rem; font-size:0.75rem; margin-top:0.5rem;" onclick="optimizePrompt('${l.id}')">Optimize Prompt Template</button>`;
        } else {
            opt_section = `<div style="color:#10b981; font-size:0.8rem; margin-top:0.5rem; font-weight:600;">✓ Optimized (Prompts version linked: v${l.optimized_prompt_id.substring(0,8)})</div>`;
        }
        
        const card = document.createElement("div");
        card.className = "timeline-card";
        card.style.borderLeft = "4px solid #ef4444";
        card.innerHTML = `
            <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:0.4rem;">
                <span style="color:#ef4444;">${l.prompt_name} Failure Case [${l.failure_type.toUpperCase()}]</span>
                <span>Eval score: ${l.evaluation_score}/1.0</span>
            </div>
            <p style="font-size:0.85rem; color:#9ca3af;">Query: <i>"${l.input_text}"</i></p>
            <p style="font-size:0.85rem; color:#9ca3af; margin:0.3rem 0;">Response: <span style="color:#ef4444;">"${l.output_text}"</span></p>
            <p style="font-size:0.85rem; color:#d1d5db;">Correction detail: "${l.correction_details || "No details provided"}"</p>
            ${opt_section}
            <div style="font-size:0.75rem; color:#9ca3af; margin-top:0.5rem;">Logged: ${dt}</div>
        `;
        feed.appendChild(card);
    });
}

async function logFailureCase() {
    const prompt_name = document.getElementById("select-failure-prompt").value;
    const input_text = document.getElementById("input-failure-query").value;
    const output_text = document.getElementById("input-failure-response").value;
    const failure_type = document.getElementById("select-failure-type").value;
    const evaluation_score = parseFloat(document.getElementById("input-failure-score").value);
    const correction_details = document.getElementById("input-failure-corrections").value;
    
    if (!input_text || !output_text) return;
    
    const res = await apiPost("/improvement/logs", {
        prompt_name, input_text, output_text, failure_type, evaluation_score, correction_details
    });
    
    if (res) {
        document.getElementById("input-failure-query").value = "";
        document.getElementById("input-failure-response").value = "";
        document.getElementById("input-failure-corrections").value = "";
        loadImprovementLogs();
    }
}

async function optimizePrompt(id) {
    const feed = document.getElementById("improvement-logs-feed");
    feed.innerHTML = "<div class='loading-placeholder'>Executing failure analyzer & prompt meta-optimizer...</div>";
    
    const response = await fetch(`${API_PREFIX}/improvement/logs/${id}/optimize`, { method: "POST" });
    if (response.ok) {
        loadImprovementLogs();
    }
}

// ==================== 12. OPERATIONS CENTER ====================
async function loadAnalyticsCenter() {
    const stats = await apiGet("/analytics/dashboard");
    if (!stats) return;
    
    document.getElementById("tile-health").innerText = "ONLINE";
    document.getElementById("tile-p95").innerText = `${stats.p95_latency}s`;
    document.getElementById("tile-success").innerText = `${stats.success_rate}%`;
    document.getElementById("tile-cost").innerText = `$${stats.total_cost.toFixed(5)}`;
    
    // Draw ops volume growth bar chart
    if (charts.ops) charts.ops.destroy();
    
    const ctx = document.getElementById("chart-ops-volumes").getContext("2d");
    charts.ops = new Chart(ctx, {
        type: "bar",
        data: {
            labels: ["Memories", "Active Tasks", "Orchestrated Sessions", "Vulnerabilities Alerts"],
            datasets: [{
                label: "Volumes Index",
                data: [stats.memory_growth, stats.tasks_active, stats.sessions, stats.total_threats],
                backgroundColor: ["#3b82f6", "#fbbf24", "#8b5cf6", "#ef4444"]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { grid: { color: "rgba(255,255,255,0.05)" }, ticks: { color: "#ffffff" } },
                x: { grid: { display: false }, ticks: { color: "#ffffff" } }
            }
        }
    });
}
