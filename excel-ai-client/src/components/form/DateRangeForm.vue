<script setup lang="ts">
import type { DateRange } from 'reka-ui'
import { Button } from '@/components/ui/button'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { RangeCalendar } from '@/components/ui/range-calendar'
import { cn } from '@/lib/utils'
import {
  CalendarDate,
  DateFormatter,
} from '@internationalized/date'
import { Calendar as CalendarIcon } from 'lucide-vue-next'
import { type Ref, h, ref } from 'vue'
import { toast } from "vue-sonner"
import { FormField, FormItem } from '@/components/ui/form';
import { VueDatePicker } from '@vuepic/vue-datepicker';
import '@vuepic/vue-datepicker/dist/main.css'
const selectedDate = ref<Date | null>(null);

const df = new DateFormatter('en-US', {
  dateStyle: 'medium',
})

const value = ref({
  start: new CalendarDate(2022, 1, 20),
  end: new CalendarDate(2022, 1, 20).add({ days: 20 }),
}) as Ref<DateRange>
async function onSubmit(values: any) {
  values.start = value.value.start ? `${value.value.start.year}-${value.value.start.month}-${value.value.start.day}` : null
  values.end = value.value.end ? `${value.value.end.year}-${value.value.end.month}-${value.value.end.day}` : null
  toast.success({
    title: 'You submitted the following values:',
    description: h('pre', { class: 'mt-2 w-[340px] rounded-md bg-slate-950 p-4' }, h('code', { class: 'text-white' }, JSON.stringify(values, null, 2))),
  })
}

const time = ref('12:00:00'); // Set an initial value for the time

</script>

<template>
  <div>
    <h3 class="text-lg font-medium">
      Date Range example
    </h3>
    <p class="text-sm text-muted-foreground">
      Select date range
    </p>
  </div>
  <Separator />
  <Form class="space-y-8" @submit.prevent="onSubmit">
    <FormField name="name">
      <FormItem>
        <Popover>
          <PopoverTrigger as-child>
            <Button variant="outline" :class="cn(
              'w-[280px] justify-start text-left font-normal',
              !value && 'text-muted-foreground',
            )">
              <CalendarIcon class="mr-2 h-4 w-4" />
              <template v-if="value.start">
                <template v-if="value.end">
                  {{ value.start }} - {{
                    value.end }}
                </template>

                <template v-else>
                  {{ value.start }}
                </template>
              </template>
              <template v-else>
                Pick a date
              </template>
            </Button>
          </PopoverTrigger>
          <PopoverContent class="w-auto p-0">
            <RangeCalendar v-model="value" initial-focus :number-of-months="2"
              @update:start-value="(startDate) => value.start = startDate" />
          </PopoverContent>
        </Popover>
      </FormItem>
      <br />

      <div class="flex justify-start">
        <Button type="submit">
          Submit
        </Button>
      </div>
    </FormField>

    <FormField v-slot="{ field, value }" name="dob">
      <FormItem class="flex flex-col">
        <Popover>
          <FormLabel>Date of birth with TIme</FormLabel>
          <PopoverTrigger as-child class="p-0">
            <div>
              <VueDatePicker v-model="selectedDate" :format="'yyyy-mm-dd'" :week-start="1"
                :disabled-dates="['2024-01-01', '2024-12-25']" />
              <p>Selected Date: {{ selectedDate }}</p>
            </div>
          </PopoverTrigger>
        </Popover>
      </FormItem>
    </FormField>
  </Form>
</template>