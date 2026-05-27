<script setup lang="ts">
import { computed, ref, Ref } from 'vue'
import { Separator } from '@/components/ui/separator'
import { Button } from '@/components/ui/button'
import { toast } from "vue-sonner"
import MQL from '@/plugins/mql'
import { Codemirror } from 'vue-codemirror'
import { json } from "@codemirror/lang-json";
import type { Extension } from "@codemirror/state";
const extensions: Ref<Extension[]> = ref([]);

const result = ref([])
function GetAllPosts() {
    new MQL()
        .setActivity('o.[GetSampleData]')
        .setData({})
        .fetch()
        .then((rs: any) => {
            const res = rs.getActivity('GetSampleData', false)
            if (rs.isValid('GetSampleData')) {
                toast.success("Data Loaded Successfully")
                result.value = res.result
                extensions.value = [json()];
            } else {
                rs.showErrorToast('GetSampleData')
            }
        })
}
const results = computed({
    get: () => JSON.stringify(result.value, null, 2),
    set: (value: string) => {
        try {
            result.value = JSON.parse(value);
        } catch (e) {
            toast.error({ title: 'error', description: 'Invalid JSON format' });
        }
    }
});


</script>

<template>
    <div>
        <h3 class="text-lg font-medium">
            MQL Request Demo
        </h3>
        <p class="text-sm text-muted-foreground">
            This is how others will see you on the site.
        </p>
    </div>
    <Separator />
    <div class="flex justify-start mt-4">
        <Button @click="GetAllPosts">
            MQL Request Demo
        </Button>
    </div>
    <Codemirror v-model="results" placeholder="Code goes here..." :autofocus="true" :indent-with-tab="true"
        :tab-size="2" :extensions="extensions" class="border border-border rounded-lg shadow-sm" />

</template>