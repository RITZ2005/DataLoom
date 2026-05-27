<template>
    <Popover v-model:open="open">
        <PopoverTrigger as-child>
            <TagsInput id="triggerElem" :aria-expanded="open" class="w-full">
                <TagsInputItem v-for="item in selectedValues" :key="item" :value="item">
                    <TagsInputItemText />
                    <TagsInputItemDelete as-child>
                        <Cross2Icon class="h-4 w-4 cursor-pointer" @click="() => removeSelection(item)" />
                    </TagsInputItemDelete>
                </TagsInputItem>
                <TagsInputInput placeholder="select.." />
            </TagsInput>
        </PopoverTrigger>
        <PopoverContent :style="{ width: triggerWidth + 'px' }" class="p-0" v-if="open"> <!-- Dynamic width -->
            <Command>
                <CommandInput class="h-9" placeholder="Search item..." />
                <CommandEmpty>No item found.</CommandEmpty>
                <CommandList>
                    <CommandGroup>
                        <CommandItem v-for="item in props.items" :key="item" :value="item"
                            @select="() => toggleSelection(item)">
                            {{ item }}
                            <CheckIcon :class="cn(
                                'ml-auto h-4 w-4',
                                selectedValues.includes(item) ? 'opacity-100' : 'opacity-0',
                            )" />
                        </CommandItem>
                    </CommandGroup>
                </CommandList>
            </Command>
        </PopoverContent>
    </Popover>
</template>
<script setup lang="ts">
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from '@/components/ui/command'
import {
    TagsInput,
    TagsInputInput,
    TagsInputItem,
    TagsInputItemDelete,
    TagsInputItemText,
} from "@/components/ui/tags-input";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from '@/components/ui/popover'
import { cn } from '@/lib/utils'
import { CheckIcon, Cross2Icon } from '@radix-icons/vue'
import { ref, watch, onMounted, onBeforeUnmount } from 'vue' // Added onBeforeUnmount

const props = defineProps<{
    items: string[]
    selectedValues: string[]
}>()

const emit = defineEmits<{
    (e: '@input', selectedValues: string[]): void
}>()

watch(() => props.selectedValues, (value) => {
    selectedValues.value = value
})
const open = ref(false)
const selectedValues = ref<string[]>(props.selectedValues)

const toggleSelection = (value: string) => {
    const index = selectedValues.value.indexOf(value)
    if (index === -1) {
        selectedValues.value.push(value)
    } else {
        selectedValues.value.splice(index, 1)
    }
    emit('@input', selectedValues.value)
}

const removeSelection = (value: string) => {
    const index = selectedValues.value.indexOf(value)
    if (index !== -1) {
        selectedValues.value.splice(index, 1)
        emit('@input', selectedValues.value)
    }
}

const triggerWidth = ref(0)

onMounted(() => {
    const updateTriggerWidth = () => {
        const triggerElement = document.getElementById('triggerElem')
        if (triggerElement) {
            triggerWidth.value = triggerElement.clientWidth
        }
    }

    updateTriggerWidth()
    window.addEventListener('resize', updateTriggerWidth)

    onBeforeUnmount(() => {
        window.removeEventListener('resize', updateTriggerWidth)
    })
})
</script>
