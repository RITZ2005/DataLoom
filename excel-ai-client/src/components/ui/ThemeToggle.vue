<template>
  <div class="flex items-center gap-1">
    <!--
    Color palette picker is intentionally disabled for now.
    Keep this block for future reuse when multi-palette switching is needed again.

    <Popover>
      <PopoverTrigger as-child>
        <Button variant="ghost" size="icon" class="rounded-full" title="Color theme">
          <Palette style="width: 20px; height: 20px;" />
        </Button>
      </PopoverTrigger>
      <PopoverContent class="w-auto p-3" align="end" :side-offset="8">
        <p class="text-xs font-medium text-muted-foreground mb-2">Accent Color</p>
        <div class="flex gap-2">
          <div
            v-for="(color, index) in colorOptions"
            :key="index"
            :title="color.name"
            :class="['color-circle', color.value, currentColor === color.value ? 'active' : '']"
            @click="setColorTheme(color.value)"
          >
            <Check v-if="currentColor === color.value" class="check-icon" />
          </div>
        </div>
      </PopoverContent>
    </Popover>
    -->

    <!-- Toggle Light/Dark Theme -->
    <Button @click="toggleTheme" variant="ghost" size="icon" class="rounded-full" title="Toggle theme">
      <Moon v-if="isDarkMode" style="width: 20px; height: 20px;" />
      <Sun v-if="!isDarkMode" style="width: 20px; height: 20px;" />
    </Button>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Moon, Sun, Check, Palette } from "lucide-vue-next";

// States
const isDarkMode = ref(false);
const currentColor = ref('');

// Color options
const colorOptions = [
  { name: 'Red', value: 'red' },
  { name: 'Rose', value: 'rose' },
  { name: 'Orange', value: 'orange' },
  { name: 'Green', value: 'green' },
  { name: 'Blue', value: 'blue' },
  { name: 'Yellow', value: 'yellow' },
  { name: 'Violet', value: 'violet' },
  { name: 'Black', value: 'black' },
];

// Functions
const applyTheme = () => {
  const root = document.documentElement;
  const lockedColor = 'green';
  const paletteClasses = ['red', 'rose', 'orange', 'green', 'blue', 'yellow', 'violet', 'black'];

  // Toggle light/dark theme
  root.classList.toggle('dark', isDarkMode.value);

  // Color palette switching is temporarily disabled; force the green palette.
  // colorOptions.forEach(color => root.classList.remove(color.value));
  // if (currentColor.value) root.classList.add(currentColor.value);
  paletteClasses.forEach(color => root.classList.remove(color));
  root.classList.add(lockedColor);
  currentColor.value = lockedColor;

  // Save preferences
  localStorage.setItem('theme', isDarkMode.value ? 'dark' : 'light');
  localStorage.setItem('color', lockedColor);
};

const toggleTheme = () => {
  isDarkMode.value = !isDarkMode.value;
  applyTheme();
};

// Color palette switching is intentionally disabled for now.
// const setColorTheme = (color: string) => {
//   currentColor.value = color;
//   applyTheme();
// };

onMounted(() => {
  const savedTheme = localStorage.getItem('theme');
  // const savedColor = localStorage.getItem('color');

  isDarkMode.value = savedTheme ? savedTheme === 'dark' : true;
  currentColor.value = 'green';

  applyTheme();
});
</script>

<style scoped>
.color-circle {
  width: 25px;
  height: 25px;
  border-radius: 50%;
  position: relative;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
  box-shadow: 0 0 0 2px transparent;
}

.color-circle:hover {
  transform: scale(1.1);
}

/* Active circle styling */
.color-circle.active {
  box-shadow: 0 0 0 3px hsl(var(--ring));
}

/* Check icon for active color */
.check-icon {
  color: white;
  width: 18px;
  height: 18px;
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
}

/* Define color classes */
.red {
  background-color: #ef4444; /* Red */
}

.rose {
  background-color: #f43f5e; /* Rose */
}

.orange {
  background-color: #f97316; /* Orange */
}

.green {
  background-color: #10b981; /* Green */
}

.blue {
  background-color: #3b82f6; /* Blue */
}

.yellow {
  background-color: #facc15; /* Yellow */
}

.violet {
  background-color: #8b5cf6; /* Violet */
}

.black {
  background-color: #171717; /* Black */
  box-shadow: 0 0 0 1px rgba(255,255,255,0.15);
}
</style>
