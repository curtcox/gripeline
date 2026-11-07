import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests',timeout:120000,workers:1,use:{baseURL:'http://127.0.0.1:8766'},webServer:{command:'python3 -m http.server 8766 --bind 127.0.0.1 --directory ../site/_site',url:'http://127.0.0.1:8766/editor/',reuseExistingServer:false}});
