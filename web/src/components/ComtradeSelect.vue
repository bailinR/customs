<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";

const props = defineProps({
  label: { type: String, required: true },
  modelValue: { type: [String, Number], default: "" },
  options: { type: Array, default: () => [] },
  groups: { type: Array, default: null },
  placeholder: { type: String, default: "" },
  disabled: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue"]);

const open = ref(false);
const query = ref("");
const root = ref(null);
const inputRef = ref(null);

const allOptions = computed(() => {
  if (props.groups?.length) {
    return props.groups.flatMap((g) => g.options);
  }
  return props.options;
});

const selectedOption = computed(() => {
  if (props.modelValue === "" || props.modelValue == null) return null;
  const found = allOptions.value.find(
    (o) => String(o.value) === String(props.modelValue)
  );
  if (found) return found;
  return { value: props.modelValue, label: String(props.modelValue) };
});

function matchQuery(label) {
  const q = query.value.trim().toLowerCase();
  if (!q) return true;
  return String(label).toLowerCase().includes(q);
}

const filteredFlat = computed(() => {
  if (props.groups?.length) return [];
  return props.options.filter((o) => matchQuery(o.label));
});

const filteredGroups = computed(() => {
  if (!props.groups?.length) return [];
  return props.groups
    .map((g) => ({
      label: g.label,
      options: g.options.filter((o) => matchQuery(o.label)),
    }))
    .filter((g) => g.options.length);
});

function selectOption(opt) {
  emit("update:modelValue", opt.value);
  query.value = "";
  open.value = false;
}

function clearTag(event) {
  event.stopPropagation();
  emit("update:modelValue", "");
  query.value = "";
}

async function openDropdown() {
  if (props.disabled) return;
  open.value = true;
  await nextTick();
  inputRef.value?.focus();
}

function toggleDropdown() {
  if (props.disabled) return;
  if (open.value) {
    open.value = false;
  } else {
    openDropdown();
  }
}

function onControlClick() {
  if (!open.value) openDropdown();
}

function onClickOutside(event) {
  if (root.value && !root.value.contains(event.target)) {
    open.value = false;
    query.value = "";
  }
}

onMounted(() => document.addEventListener("mousedown", onClickOutside));
onBeforeUnmount(() => document.removeEventListener("mousedown", onClickOutside));
</script>

<template>
  <div ref="root" class="comtrade-select" :class="{ open, disabled }">
    <div class="comtrade-select-label">{{ label }}</div>

    <div class="comtrade-select-control" @click="onControlClick">
      <div class="comtrade-select-tags">
        <span v-if="selectedOption" class="comtrade-tag">
          {{ selectedOption.label }}
          <button type="button" class="comtrade-tag-remove" aria-label="Remove" @click="clearTag">
            ×
          </button>
        </span>
        <input
          ref="inputRef"
          v-model="query"
          class="comtrade-select-input"
          type="text"
          :placeholder="selectedOption ? '' : placeholder"
          :disabled="disabled"
          @focus="openDropdown"
        />
      </div>
      <button
        type="button"
        class="comtrade-select-chevron"
        :disabled="disabled"
        aria-label="Toggle"
        @click.stop="toggleDropdown"
      >
        <span class="chevron-icon" :class="{ up: open }" />
      </button>
    </div>

    <div v-if="open" class="comtrade-select-dropdown">
      <template v-if="filteredGroups.length">
        <div v-for="group in filteredGroups" :key="group.label" class="comtrade-select-group">
          <div class="comtrade-select-group-label">{{ group.label }}</div>
          <button
            v-for="opt in group.options"
            :key="opt.value"
            type="button"
            class="comtrade-select-option"
            :class="{ active: String(opt.value) === String(modelValue) }"
            @mousedown.prevent="selectOption(opt)"
          >
            {{ opt.label }}
          </button>
        </div>
      </template>
      <template v-else>
        <button
          v-for="opt in filteredFlat"
          :key="opt.value"
          type="button"
          class="comtrade-select-option"
          :class="{ active: String(opt.value) === String(modelValue) }"
          @mousedown.prevent="selectOption(opt)"
        >
          {{ opt.label }}
        </button>
      </template>
      <div
        v-if="!filteredFlat.length && !filteredGroups.length"
        class="comtrade-select-empty"
      >
        No matches
      </div>
    </div>
  </div>
</template>

<style scoped>
.comtrade-select {
  position: relative;
  width: 100%;
}

.comtrade-select-label {
  margin-bottom: 4px;
  font-size: 0.82rem;
  color: #333;
}

.comtrade-select-control {
  display: flex;
  align-items: stretch;
  min-height: 36px;
  border: 1px solid #bdbdbd;
  border-radius: 2px;
  background: #fff;
  cursor: text;
  overflow: visible;
}

.comtrade-select.open .comtrade-select-control {
  border-color: #888;
}

.comtrade-select-tags {
  flex: 1;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 3px 6px;
  min-width: 0;
}

.comtrade-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 2px 6px;
  background: #5a6268;
  color: #fff;
  font-size: 0.82rem;
  line-height: 1.3;
  border-radius: 2px;
}

.comtrade-tag-remove {
  border: none;
  background: transparent;
  color: #fff;
  font-size: 1rem;
  line-height: 1;
  padding: 0;
  cursor: pointer;
  opacity: 0.85;
}

.comtrade-tag-remove:hover {
  opacity: 1;
}

.comtrade-select-input {
  flex: 1;
  min-width: 48px;
  border: none;
  outline: none;
  font-size: 0.82rem;
  padding: 2px 0;
  background: transparent;
}

.comtrade-select-chevron {
  flex-shrink: 0;
  width: 32px;
  min-height: 36px;
  padding: 0;
  border: none;
  border-left: 1px solid #e0e0e0;
  background: #fafafa;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.comtrade-select-chevron:hover:not(:disabled) {
  background: #f0f0f0;
}

.chevron-icon {
  display: block;
  width: 0;
  height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid #666;
}

.chevron-icon.up {
  border-top: none;
  border-bottom: 6px solid #666;
}

.comtrade-select-dropdown {
  position: absolute;
  z-index: 20;
  top: calc(100% + 2px);
  left: 0;
  right: 0;
  max-height: 260px;
  overflow-y: auto;
  background: #fff;
  border: 1px solid #bdbdbd;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.comtrade-select-group-label {
  padding: 8px 12px 4px;
  font-size: 0.78rem;
  color: #888;
}

.comtrade-select-option {
  display: block;
  width: 100%;
  padding: 6px 12px;
  border: none;
  background: transparent;
  text-align: left;
  font-size: 0.84rem;
  color: #222;
  cursor: pointer;
}

.comtrade-select-option:hover,
.comtrade-select-option.active {
  background: #f5f5f5;
}

.comtrade-select-empty {
  padding: 10px 12px;
  color: #999;
  font-size: 0.82rem;
}

.comtrade-select.disabled {
  opacity: 0.6;
  pointer-events: none;
}
</style>
