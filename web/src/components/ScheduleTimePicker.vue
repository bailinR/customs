<script setup>
import { computed } from "vue";

const props = defineProps({
  modelValue: { type: String, default: "02:00" },
  hourId: { type: String, default: "schedule-hour" },
  minuteId: { type: String, default: "schedule-minute" },
});

const emit = defineEmits(["update:modelValue", "change"]);

const HOURS = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, "0"));
const MINUTES = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, "0"));

function pad2(n) {
  return String(n).padStart(2, "0");
}

function parseTime(value) {
  const [h = "0", m = "0"] = String(value || "02:00").split(":");
  const hour = Math.min(23, Math.max(0, Number(h) || 0));
  const minute = Math.min(59, Math.max(0, Number(m) || 0));
  return { hour: pad2(hour), minute: pad2(minute) };
}

const hour = computed(() => parseTime(props.modelValue).hour);
const minute = computed(() => parseTime(props.modelValue).minute);

function emitTime(h, m) {
  const time = `${pad2(Number(h))}:${pad2(Number(m))}`;
  emit("update:modelValue", time);
  emit("change", time);
}

function onHourChange(event) {
  emitTime(event.target.value, minute.value);
}

function onMinuteChange(event) {
  emitTime(hour.value, event.target.value);
}
</script>

<template>
  <div class="schedule-time-row">
    <select
      :id="hourId"
      class="schedule-time-select"
      :value="hour"
      @change="onHourChange"
    >
      <option v-for="h in HOURS" :key="h" :value="h">{{ h }}</option>
    </select>
    <span class="schedule-time-sep">:</span>
    <select
      :id="minuteId"
      class="schedule-time-select"
      :value="minute"
      @change="onMinuteChange"
    >
      <option v-for="m in MINUTES" :key="m" :value="m">{{ m }}</option>
    </select>
  </div>
</template>
