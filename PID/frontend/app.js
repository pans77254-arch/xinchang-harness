const { createApp, ref, computed, onMounted } = Vue;

const TYPE_LABEL = {
  missing_catalog: "缺少目录",
  missing_file: "目录有、文件夹无",
  extra_file: "文件夹有、目录无",
  unidentified_file: "未识别文件号",
  file_no_mismatch: "文件号不一致",
  public_mismatch: "不一致",
  name_mismatch: "名称不一致",
  revision_mismatch: "版次不一致",
  sheet_count_mismatch: "实际页数不一致",
  printed_sheet_mismatch: "所写张数不一致",
  missing_field: "字段未抽出",
  missing_frame: "未检出图框",
  tool_error: "工具失败",
  equivalent_mismatch: "折合不一致",
  pid_paper_mismatch: "PID图幅不符",
  pid_not_found: "未识别到PID图纸",
  pid_seq_gap: "PID页号缺号",
  pid_seq_duplicate: "PID页号重复",
  pid_seq_off_ladder: "PID页号不合间隔",
  pid_seq_total_mismatch: "PID总页数不符",
  pid_seq_unparseable: "PID页号未抽出",
  pid_seq_parity: "PID页号奇偶不符",
  expect_mismatch: "属性不符",
};

const PUBLIC_LABEL = {
  project_no: "项目号",
  project_name: "项目名称",
  discipline: "专业",
  stage: "阶段",
  date: "日期",
  file_no: "文件号",
  doc_title: "资料名称",
  revision: "版次",
  sheet_count: "张数",
};

const STATUS_LABEL = { pending: "待复核", confirmed: "已确认", rejected: "已驳回" };

createApp({
  setup() {
    const folder = ref("");
    const skills = ref([]);
    const selectedSkills = ref([]);
    const skillText = ref("");
    const workflowText = ref("");
    const reviseText = ref("");
    const revising = ref(false);
    const skillBaseline = ref("");
    const workflowBaseline = ref("");
    const skillSaved = ref("");
    const skillError = ref("");
    const saving = ref(false);
    const running = ref(false);
    const error = ref("");
    const result = ref(null);

    const previewPath = ref("");
    const previewPage = ref(1);
    const previewDeskew = ref(true);
    const previewSkewMode = ref("auto");
    const previewSkewMax = ref(15);
    const previewSkewMin = ref(0.5);
    const previewSkewFixed = ref(0);
    const previewBinarize = ref(true);
    const previewThresholdMethod = ref("otsu");
    const previewThresholdValue = ref(127);
    const previewing = ref(false);
    const previewError = ref("");
    const previewResult = ref(null);

    const highCount = computed(() => (result.value?.issues || []).filter((item) => item.severity === "high").length);
    const pendingCount = computed(() => (result.value?.issues || []).filter((item) => item.review_status === "pending").length);
    const publicFields = computed(() => {
      const data = result.value?.toc?.public || {};
      return Object.keys(PUBLIC_LABEL)
        .filter((key) => data[key])
        .map((key) => ({ label: PUBLIC_LABEL[key], value: data[key] }));
    });
    const pidFilesText = computed(() => {
      const value = result.value?.file_types?.pid;
      const pids = Array.isArray(value) ? value : [value].filter(Boolean);
      return pids.length ? pids.join('、') : '未识别';
    });
    const verdicts = computed(() => {
      const bySkill = {};
      (result.value?.issues || []).forEach((item) => {
        const key = item.skill_id || "未知";
        bySkill[key] = (bySkill[key] || 0) + 1;
      });
      return selectedSkills.value.map((id) => {
        const skill = skills.value.find((item) => item.id === id) || {};
        const count = bySkill[id] || 0;
        return { id, name: skill.name || id, basis: skill.basis || "", count, pass: count === 0 };
      });
    });

    function typeLabel(issue) {
      const type = typeof issue === "string" ? issue : issue?.type;
      if (type === "public_mismatch") {
        const matched = String(issue?.desc || "").match(/(\S+)与目录不一致/);
        if (matched) return `${matched[1]}不一致`;
      }
      return TYPE_LABEL[type] || type;
    }
    function statusLabel(status) {
      return STATUS_LABEL[status] || status;
    }

    async function loadSkills() {
      const response = await fetch("/api/skills");
      skills.value = await response.json();
      if (!selectedSkills.value.length) {
        selectedSkills.value = skills.value.filter((item) => item.enabled).map((item) => item.id);
      }
      const detail = await fetch("/api/skills/form.toc_index");
      if (detail.ok) {
        const data = await detail.json();
        skillText.value = data.yaml || "";
        skillBaseline.value = skillText.value;
        workflowText.value = data.workflow_yaml || "";
        workflowBaseline.value = workflowText.value;
      }
    }

    async function reviseSkill() {
      skillError.value = "";
      skillSaved.value = "";
      if (!reviseText.value.trim()) {
        skillError.value = "请先写出要改的审查要求。";
        return;
      }
      revising.value = true;
      try {
        const response = await fetch("/api/skills/form.toc_index/revise", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: reviseText.value.trim() }),
        });
        const data = await response.json();
        if (!response.ok || !data.ok) {
          skillError.value = data.unsupported || data.summary || data.detail || "这条要求现在的算子做不到。";
          return;
        }
        if (data.change_skill && data.skill_yaml) skillText.value = data.skill_yaml;
        else if (data.yaml) skillText.value = data.yaml;
        if (data.change_workflow && data.workflow_yaml) workflowText.value = data.workflow_yaml;
        const parts = [];
        if (data.change_skill) parts.push("Skill");
        if (data.change_workflow) parts.push("workflow");
        skillSaved.value = (data.summary || "已生成草稿") + `（改了 ${parts.join(" 和 ") || "内容"}）。还没保存，确认后点保存规则。`;
      } catch (exc) {
        skillError.value = "无法连接审查服务。";
      } finally {
        revising.value = false;
      }
    }

    async function saveSkill() {
      skillError.value = "";
      skillSaved.value = "";
      saving.value = true;
      try {
        const response = await fetch("/api/skills/form.toc_index", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ yaml: skillText.value, workflow_yaml: workflowText.value }),
        });
        const data = await response.json();
        if (!response.ok) {
          skillError.value = data.detail || "没有保存。";
          return;
        }
        skillSaved.value = "已保存。下一次审查按这份 Skill 与 workflow 执行。";
        await loadSkills();
      } catch (exc) {
        skillError.value = "无法连接审查服务。";
      } finally {
        saving.value = false;
      }
    }

    async function startReview() {
      error.value = "";
      if (!folder.value.trim()) {
        error.value = "请填写设计文件所在文件夹。";
        return;
      }
      if (!selectedSkills.value.length) {
        error.value = "请至少勾选一个审查点。";
        return;
      }
      if (skillText.value !== skillBaseline.value || workflowText.value !== workflowBaseline.value) {
        error.value = "Skill 或 workflow 已修改，还没保存。请先点保存规则，看到已保存后再审查。";
        return;
      }
      running.value = true;
      result.value = null;
      try {
        const response = await fetch("/api/review/folder", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ folder: folder.value.trim(), skill_ids: selectedSkills.value }),
        });
        const data = await response.json();
        if (!response.ok) {
          error.value = data.detail || "审查没有完成。";
          return;
        }
        result.value = data;
        history.replaceState(null, "", `/?task=${data.task_id}`);
      } catch (exc) {
        error.value = "无法连接审查服务。";
      } finally {
        running.value = false;
      }
    }

    async function runPreprocess() {
      previewError.value = "";
      if (!previewPath.value.trim()) {
        previewError.value = "请填写 PID 图纸或图片的路径，也可以直接填文件夹（自动取其中的 PID）。";
        return;
      }
      previewing.value = true;
      previewResult.value = null;
      try {
        const response = await fetch("/api/preprocess", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            file_path: previewPath.value.trim(),
            page: Number(previewPage.value) || 1,
            deskew: previewDeskew.value,
            skew_mode: previewSkewMode.value,
            skew_max: Number(previewSkewMax.value) || 15,
            skew_min: Number(previewSkewMin.value) || 0,
            skew_fixed: Number(previewSkewFixed.value) || 0,
            binarize: previewBinarize.value,
            threshold_method: previewThresholdMethod.value,
            threshold_value: Number(previewThresholdValue.value) || 127,
          }),
        });
        const data = await response.json();
        if (!response.ok) {
          previewError.value = data.detail || "预处理没有完成。";
          return;
        }
        previewResult.value = data;
      } catch (exc) {
        previewError.value = "无法连接审查服务。";
      } finally {
        previewing.value = false;
      }
    }

    async function setStatus(issue, reviewStatus) {
      const response = await fetch(`/api/tasks/${result.value.task_id}/issues/${issue.issue_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_status: reviewStatus }),
      });
      if (response.ok) result.value = await response.json();
    }

    onMounted(async () => {
      await loadSkills();
      const taskId = new URLSearchParams(location.search).get("task");
      if (!taskId) return;
      const response = await fetch(`/api/tasks/${taskId}/result`);
      if (response.ok) {
        result.value = await response.json();
        if (result.value.folder) folder.value = result.value.folder;
      }
    });

    return {
      folder, skills, selectedSkills, skillText, workflowText, skillSaved, skillError, saving, running, error, result, highCount, pendingCount, publicFields, pidFilesText, verdicts,
      previewPath, previewPage, previewDeskew, previewSkewMode, previewSkewMax, previewSkewMin, previewSkewFixed,
      previewBinarize, previewThresholdMethod, previewThresholdValue, previewing, previewError, previewResult, runPreprocess,
      typeLabel, statusLabel, startReview, saveSkill, reviseSkill, reviseText, revising, setStatus,
    };
  },
  template: `
    <main class="sheet">
      <header class="plate">
        <div>
          <p class="kicker">长庆工程设计</p>
          <p>形式审查 · 项目级</p>
        </div>
        <div>
          <h1>形式审查</h1>
          <p>页面只把文件夹交给审查服务。目录、图框和比对都在智能体平台里完成，这里只展示问题并做人工复核。</p>
        </div>
        <div>
          <p class="kicker">审查点</p>
          <p>{{ selectedSkills.join(' / ') || '未勾选' }}</p>
        </div>
      </header>

      <section class="panel skill-editor">
        <div class="skill-head">
          <h2>Skill 与 workflow</h2>
          <button :disabled="saving || running" @click="saveSkill">{{ saving ? '保存中' : '保存规则' }}</button>
        </div>
        <p class="hint">Skill 决定审什么；workflow.yaml 决定审查流程。用下面这句话改规则，转换智能体会判断改哪一份。</p>
        <div class="revise">
          <input v-model="reviseText" type="text" placeholder="例如：审查日期是否一致，其余无需审查；或：PDF 不要再裁图框" :disabled="revising || saving || running" />
          <button :disabled="revising || saving || running" @click="reviseSkill">{{ revising ? '修改中' : '按这句话改' }}</button>
        </div>
        <p class="kicker">Skill（ai/rules）</p>
        <textarea v-model="skillText" spellcheck="false" :disabled="saving || running || revising"></textarea>
        <p class="kicker">workflow（ai/workflows）</p>
        <textarea v-model="workflowText" spellcheck="false" :disabled="saving || running || revising"></textarea>
        <p class="hint" v-if="skillSaved">{{ skillSaved }}</p>
        <p class="error" v-if="skillError">{{ skillError }}</p>
      </section>

      <section class="panel preprocess">
        <div class="skill-head">
          <h2>图像预处理预览 · 二值化与倾斜校正</h2>
          <button :disabled="previewing" @click="runPreprocess">{{ previewing ? '处理中' : '预览处理' }}</button>
        </div>
        <p class="hint">选一张 PID 图纸（PDF 或图片，也可以直接填文件夹，自动取其中的工艺自控流程图）。这里改的是临时参数，正式审查用 Skill 里的 preprocess 配置。</p>
        <div class="pre-grid">
          <label for="pre-path">文件或文件夹</label>
          <input id="pre-path" v-model="previewPath" type="text" placeholder="例如 /data/.../某站形式审查" :disabled="previewing" />
          <label for="pre-page">页码（PDF）</label>
          <input id="pre-page" v-model="previewPage" type="number" min="1" :disabled="previewing" />
          <label class="check"><input type="checkbox" v-model="previewDeskew" :disabled="previewing" />倾斜校正</label>
          <select v-model="previewSkewMode" :disabled="previewing || !previewDeskew">
            <option value="auto">auto · 自动检测</option>
            <option value="fixed">fixed · 固定角度</option>
            <option value="off">off · 不矫正</option>
          </select>
          <label for="pre-max">检测上限 ±°</label>
          <input id="pre-max" v-model="previewSkewMax" type="number" step="0.5" :disabled="previewing || !previewDeskew" />
          <label for="pre-min">最小矫正角 °</label>
          <input id="pre-min" v-model="previewSkewMin" type="number" step="0.1" :disabled="previewing || !previewDeskew" />
          <label for="pre-fixed">固定矫正角 °</label>
          <input id="pre-fixed" v-model="previewSkewFixed" type="number" step="0.5" :disabled="previewing || previewSkewMode !== 'fixed'" />
          <label class="check"><input type="checkbox" v-model="previewBinarize" :disabled="previewing" />二值化</label>
          <select v-model="previewThresholdMethod" :disabled="previewing || !previewBinarize">
            <option value="otsu">otsu · 自动阈值</option>
            <option value="fixed">fixed · 固定阈值</option>
            <option value="adaptive">adaptive · 自适应</option>
          </select>
          <label for="pre-thr">阈值</label>
          <input id="pre-thr" v-model="previewThresholdValue" type="number" min="1" max="255" :disabled="previewing || previewThresholdMethod !== 'fixed'" />
        </div>
        <p class="error" v-if="previewError">{{ previewError }}</p>
        <div class="pre-view" v-if="previewResult">
          <figure>
            <figcaption>原图</figcaption>
            <img :src="previewResult.src_url" alt="原图" />
          </figure>
          <figure>
            <figcaption>
              处理后：倾斜 {{ previewResult.skew_angle }}°{{ previewResult.corrected ? '（已矫正）' : '（未矫正）' }}{{ previewResult.threshold_method ? '，二值化 ' + previewResult.threshold_method : '，未二值化' }}
            </figcaption>
            <img :src="previewResult.out_url" alt="预处理结果" />
          </figure>
        </div>
      </section>

      <section class="desk">
        <aside class="panel">
          <label for="folder">设计文件夹</label>
          <input id="folder" v-model="folder" type="text" placeholder="例如 C:\\项目\\某站形式审查" :disabled="running" />
          <ul class="skills">
            <li v-for="skill in skills" :key="skill.id">
              <label class="skill-pick">
                <input type="checkbox" :value="skill.id" v-model="selectedSkills" :disabled="!skill.enabled || running" />
                <span>{{ skill.name }}</span>
              </label>
              <span :class="selectedSkills.includes(skill.id) ? 'on' : 'off'">
                {{ skill.enabled ? (selectedSkills.includes(skill.id) ? '本次执行' : '未纳入本次') : '未启用' }}
              </span>
              <p class="basis" v-if="skill.basis">依据：{{ skill.basis }}</p>
            </li>
          </ul>
          <div class="row">
            <button :disabled="running" @click="startReview">{{ running ? '审查进行中' : '开始审查' }}</button>
          </div>
          <p class="hint" v-if="running">正在转换目录、裁图框并抽取字段，通常需要一两分钟。</p>
          <p class="error" v-if="error">{{ error }}</p>
        </aside>

        <section class="panel" v-if="!result">
          <h2>等待审查结果</h2>
          <p class="hint">提交文件夹后，这里会列出目录公共字段、目录表、各文件抽出的标题栏，以及需要复核的问题。</p>
        </section>

        <section v-else>
          <div class="stats">
            <div class="stat"><b>{{ result.issues.length }}</b><span>问题</span></div>
            <div class="stat"><b>{{ highCount }}</b><span>强制性</span></div>
            <div class="stat"><b>{{ pendingCount }}</b><span>待复核</span></div>
            <div class="stat" v-if="result.toc && result.toc.entries && result.toc.entries.length"><b>{{ result.toc.entries.length }}</b><span>目录条目</span></div>
          </div>

          <div class="panel" v-if="result.file_types">
            <h2>文件识别</h2>
            <div class="fields">
              <span>目录</span>
              <strong>{{ result.file_types.catalog || '未识别' }}</strong>
              <span>工艺自控流程图</span>
              <strong>{{ pidFilesText }}</strong>
              <span>平面图</span>
              <strong>{{ result.file_types.plan || '未识别' }}</strong>
            </div>
          </div>

          <div class="panel" v-if="verdicts.length">
            <h2>审查结论</h2>
            <ul class="skills">
              <li v-for="verdict in verdicts" :key="verdict.id">
                <span>{{ verdict.name }}</span>
                <span :class="verdict.pass ? 'on' : 'off'">{{ verdict.pass ? '通过' : verdict.count + ' 个问题' }}</span>
                <p class="basis" v-if="verdict.basis">依据：{{ verdict.basis }}</p>
              </li>
            </ul>
          </div>

          <div class="panel">
            <h2>审查问题</h2>
            <p class="hint" v-if="!result.issues.length">这次没有发现问题。</p>
            <article class="issue" v-for="issue in result.issues" :key="issue.issue_id">
              <span class="tag" :class="issue.severity">{{ typeLabel(issue) }}</span>
              <div>
                <h3>{{ issue.drawing_no || '项目' }}</h3>
                <p>{{ issue.desc }}</p>
                <p v-if="issue.basis">依据：{{ issue.basis }}</p>
                <p v-if="issue.suggestion">建议：{{ issue.suggestion }}</p>
              </div>
              <div class="actions">
                <span class="state">{{ statusLabel(issue.review_status) }}</span>
                <button class="ghost" @click="setStatus(issue, 'confirmed')">确认</button>
                <button class="ghost" @click="setStatus(issue, 'rejected')">驳回</button>
              </div>
            </article>
          </div>

          <div class="panel block" v-if="publicFields.length">
            <h2>目录页眉 · 公共字段</h2>
            <div class="fields">
              <template v-for="field in publicFields" :key="field.label">
                <span>{{ field.label }}</span>
                <strong>{{ field.value }}</strong>
              </template>
            </div>
          </div>

          <div class="panel block" v-if="result.toc && result.toc.entries && result.toc.entries.length">
            <h2>目录表</h2>
            <table>
              <thead>
                <tr><th>序号</th><th>文件号</th><th>名称</th><th>版次</th><th>自然张数</th><th>备注</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in result.toc.entries" :key="row.file_no">
                  <td>{{ row.seq }}</td><td>{{ row.file_no }}</td><td>{{ row.name }}</td>
                  <td>{{ row.revision }}</td><td>{{ row.sheet_count }}</td><td>{{ row.remark }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="panel block" v-if="result.files && result.files.length">
            <h2>各文件抽出的标题信息</h2>
            <table>
              <thead>
                <tr><th>文件</th><th>文件号</th><th>名称</th><th>阶段</th><th>版次</th><th>页数</th></tr>
              </thead>
              <tbody>
                <tr v-for="file in result.files" :key="file.file">
                  <td>{{ file.file }}</td><td>{{ file.file_no }}</td><td>{{ file.name }}</td>
                  <td>{{ file.stage }}</td><td>{{ file.revision }}</td><td>{{ file.page_count }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <details>
            <summary>审查过程</summary>
            <pre class="log">{{ (result.logs || []).join('\\n') }}</pre>
          </details>
        </section>
      </section>
    </main>
  `,
}).mount("#app");
