import { createClient } from '@supabase/supabase-js'

// Replace with your Supabase project URL and anon key
const supabaseUrl = 'https://kzaqvxensdknjpjlkthi.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imt6YXF2eGVuc2RrbmpwamxrdGhpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg5MTE5MDEsImV4cCI6MjEwNDQ4NzkwMX0.yJvooAyJKx90mg2ZRYfViaRxATGS9A-L9CHm_RXY87A'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
