import io,json,os,shutil,struct,tempfile,unittest
from pathlib import Path
from unittest.mock import patch as mock_patch
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
from sources import RomSource
from configs import discover,json_read
from intents import donor_intents
from native import inverse_table
from native_extra import surfaceflinger,sensor_library
from locator import resolve,layouts
from research_native import Elf
from rom_io import Layout,metadata,new_session,commit,restore,RECEIPT
from patcher import patch
from cil_policy import merge,RULES

ROOT=Path(__file__).resolve().parent;REF=ROOT/'reference'
if not REF.exists():REF=ROOT.parent/'reference'
if os.environ.get('MIO_TEST_REFERENCE'):REF=Path(os.environ['MIO_TEST_REFERENCE'])
EXAMPLE=REF/'example_inputs'

class FixtureTests(unittest.TestCase):
    def fixture(self,root):
        for p,text in {'system/system/etc/a':'old','vendor/etc/a':'vendor',
                       'config/system_fs_config':'system/system/etc/a 0 0 0644\n',
                       'config/system_file_contexts':'/system/system/etc/a u:object_r:system_file:s0\n',
                       'config/vendor_fs_config':'vendor/etc/a 0 0 0644\n',
                       'config/vendor_file_contexts':'/vendor/etc/a u:object_r:vendor_configs_file:s0\n'}.items():
            q=root/p;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(text)
    def test_transaction_failure_and_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'ROM';self.fixture(root);layout=Layout(root);session=new_session(layout)
            with self.assertRaises(OSError):commit(layout,session,{'system/system/etc/a':b'changed','vendor/etc/new':b'new'},
                                                  {'changed_partitions':['system','vendor']},fail_after=2)
            self.assertEqual((root/'system/system/etc/a').read_text(),'old');self.assertFalse((root/'vendor/etc/new').exists())
            session=new_session(layout);commit(layout,session,{'system/system/etc/a':b'changed'},{'changed_partitions':['system']})
            self.assertTrue((root/RECEIPT).is_file());restore(session,lambda _:None)
            self.assertEqual((root/'system/system/etc/a').read_text(),'old');self.assertFalse((root/RECEIPT).exists())
    def test_double_system_metadata_and_no_props(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'ROM';self.fixture(root);layout=Layout(root)
            out,specs,_=metadata(layout,{'system/etc/a':b'x','vendor/etc/cos_color/new.xml':b'<a/>'})
            self.assertIn(b'system/system/etc/a 0 0 0644',out['config/system_fs_config'])
            self.assertEqual(specs['vendor/etc/cos_color/new.xml']['label'],'u:object_r:vendor_configs_file:s0')
            self.assertNotIn('system/etc/a',out)
    def test_cil_idempotence_and_preservation(self):
        text='; existing\n(type test)\n(typepermissive sysfs_oled_hbm)\n'
        after=merge(text);self.assertEqual(merge(after),after);self.assertTrue(after.startswith(text.rstrip()))
        for r in RULES.splitlines():self.assertEqual(after.count(r),1)
    def test_locator_follows_instruction_not_old_offset(self):
        class Fake:
            def __init__(self,words):self.symbols={'f':(0x1000,len(words)*4)};self.data=struct.pack('<'+'I'*len(words),*words)
            def read(self,a,n):return self.data[a-0x1000:a-0x1000+n]
        rule={'name':'f','patterns':[{'words':[0x1234,0x5678],'masks':[0xffffffff]*2,'anchor':1}]}
        self.assertEqual(resolve(Fake([0,0x1234,0x5678]),rule),0x1008)
        self.assertEqual(resolve(Fake([0,0,0,0x1234,0x5678]),rule),0x1010)
        with self.assertRaises(ValueError):resolve(Fake([0x1234,0x5678,0x1234,0x5678]),rule)

@unittest.skipUnless(EXAMPLE.exists(),'Reference inputs not installed')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.donor=RomSource(EXAMPLE/'OP13_ColorOS');cls.panel=discover(cls.donor)[0][0]
        cls.binaries=[]
        for target in (EXAMPLE/'OriginOS_PD2620/system/system/bin/surfaceflinger',
                       REF/'OP13T_captured_inputs/target/system/bin/surfaceflinger'):
            binary,report=surfaceflinger(target.read_bytes(),cls.panel,donor_intents(cls.donor))
            cls.binaries.append((binary,report,target.read_bytes()))
    @classmethod
    def tearDownClass(cls):cls.donor.close()
    def emulator(self,data):
        u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);e=ELFFile(io.BytesIO(data))
        for s in e.iter_segments():
            if s['p_type']!='PT_LOAD':continue
            start=s['p_vaddr']&~4095;end=(s['p_vaddr']+s['p_memsz']+4095)&~4095
            u.mem_map(start,end-start);u.mem_write(s['p_vaddr'],data[s['p_offset']:s['p_offset']+s['p_filesz']])
        return u
    def test_both_versions_native_unified_roundtrip(self):
        _,inverse,physical=inverse_table(self.panel)
        for data,report,original in self.binaries:
            u=self.emulator(data);heap,stack,callback=0x2000000,0x3000000,0x4000000
            for addr,size in ((heap,0x10000),(stack,0x10000),(callback,0x1000)):u.mem_map(addr,size)
            controller,manager,device,output,vtable=[heap+i*0x1000 for i in range(5)]
            fields={k:v['value'] for k,v in report['target_member_layout'].items()}
            u.mem_write(controller+fields['unified_manager'],struct.pack('<Q',manager))
            u.mem_write(controller+fields['unified_max'],struct.pack('<I',self.panel.maximum))
            u.mem_write(manager+fields['dbm_device'],struct.pack('<Q',device))
            u.mem_write(device+0x38,struct.pack('<QQ',output,0));u.mem_write(output,struct.pack('<Q',vtable))
            u.mem_write(vtable+0x48,struct.pack('<Q',callback));u.mem_write(callback,bytes.fromhex('c0035fd6'))
            seen=[]
            def hook(uc,addr,size,_):
                if addr==callback:seen.append(struct.unpack('<f',struct.pack('<I',uc.reg_read(UC_ARM64_REG_S0)))[0])
            u.hook_add(UC_HOOK_CODE,hook);u.reg_write(UC_ARM64_REG_SP,stack+0x8000)
            u.reg_write(UC_ARM64_REG_X19,controller)
            def f32(v):return struct.unpack('<f',struct.pack('<f',v))[0]
            for dbv in range(self.panel.maximum+1):
                u.reg_write(UC_ARM64_REG_X21,dbv);u.reg_write(UC_ARM64_REG_X22,0xe0000000)
                u.reg_write(UC_ARM64_REG_X30,callback+0x80)
                u.emu_start(report['unified']['site'],report['unified']['continue'],count=1600)
                self.assertEqual(u.reg_read(UC_ARM64_REG_PC),report['unified']['continue'])
                self.assertEqual(u.reg_read(UC_ARM64_REG_X21),dbv)
                self.assertEqual(u.reg_read(UC_ARM64_REG_SP),stack+0x8000)
                self.assertTrue(seen)
                actual=0 if seen[-1]==-1 else physical[int(f32(1+f32((self.panel.logical_max-1)*seen[-1])))]
                self.assertEqual(actual,0 if dbv==0 else physical[max(1,inverse[dbv])])
    def test_unified_sites_differ_by_more_than_symbol_rebase(self):
        offsets=[]
        for data,r,original in self.binaries:
            e=Elf(original);offsets.append(r['unified']['site']-e.symbols[r['unified']['function']][0])
        self.assertNotEqual(offsets[0],offsets[1])
    def test_elf_dynamic_dependencies_unchanged(self):
        for data,r,original in self.binaries:
            a,b=ELFFile(io.BytesIO(original)),ELFFile(io.BytesIO(data));self.assertEqual(a.header,b.header)
            for name in ('.dynamic','.dynstr','.rela.dyn','.rela.plt'):
                self.assertEqual(a.get_section_by_name(name).data(),b.get_section_by_name(name).data())
    def test_standard_lux_alias_and_other_sensor_dispatch(self):
        original=(EXAMPLE/'OriginOS_PD2620/system/system/lib64/libsensorservice_ex.so').read_bytes()
        data,r=sensor_library(original);dest=r['destinations']
        for handle,kind,want in [(1001,5,'mio_policy_process'),(1001,66551,'mio_policy_process'),
                                 (1701,66551,'mio_after_policy'),(1234,5,'mio_under_light')]:
            u=self.emulator(data);event=0x2000000;u.mem_map(event,4096)
            payload=bytearray(104);struct.pack_into('<iii',payload,0,104,handle,kind);struct.pack_into('<f',payload,24,80000)
            u.mem_write(event,bytes(payload));u.reg_write(UC_ARM64_REG_X19,event);u.reg_write(UC_ARM64_REG_X0,1)
            seen=[]
            def stop(uc,addr,size,_):
                if addr in dest.values():seen.append(addr);uc.emu_stop()
            u.hook_add(UC_HOOK_CODE,stop);u.emu_start(r['site'],0,count=40)
            self.assertEqual(seen,[dest[want]]);self.assertEqual(bytes(u.mem_read(event,104)),payload)
    def test_13t_own_panel_and_cwb(self):
        with RomSource(REF/'OP13T_captured_inputs/donor') as donor:
            p,_,cwb=discover(donor);self.assertEqual(cwb[0]['pixels'],1482)
            self.assertEqual(cwb[0]['rect'],[732,100,771,138])
            data,r=surfaceflinger(self.binaries[1][2],p[0],donor_intents(donor));self.assertEqual(r['physical_maximum'],p[0].maximum)
    def test_previous_hand_patch_can_be_relocated(self):
        old=(REF/'OP13_BC06_before_after/stage/module/system/bin/surfaceflinger').read_bytes()
        data,r=surfaceflinger(old,self.panel,donor_intents(self.donor));self.assertEqual(r['unified']['previous_hand_patch'],'BC06')

@unittest.skipUnless(EXAMPLE.exists(),'Reference inputs not installed')
class IntegrationTests(unittest.TestCase):
    def test_13t_capture_preserves_sensor_and_exports_cil(self):
        from build_capture_bundle import capture_fixture
        with tempfile.TemporaryDirectory(prefix='mio_13t_rules_') as tmp:
            target=capture_fixture(REF/'OP13T_captured_inputs/target',Path(tmp)/'OriginOS')
            sensor=(target/'system/lib64/libsensorservice.so').read_bytes()
            session,r=patch(target,REF/'OP13T_captured_inputs/donor',sensor_mode='preserve',cil_mode='rules-only',log=lambda _:None)
            self.assertEqual((target/'system/lib64/libsensorservice.so').read_bytes(),sensor)
            self.assertFalse((target/'system/lib64/libsensorservice_ex.so').exists())
            self.assertFalse(r['lux']['patched']);self.assertFalse(r['cil']['compiled'])
            self.assertEqual((session/'需要添加的SELinux规则.cil').read_text(encoding='utf8').strip(),RULES)
            sre=json_read((target/'system/etc/LcmConfig/LcmSreConfig.json').read_text())
            self.assertTrue(all(p['hbmMap_auto']==[3515,4094] for x in sre for p in x['panel']))

    def test_real_patch_repeat_restore_and_CIL(self):
        with tempfile.TemporaryDirectory(prefix='mio_origin_integration_') as tmp:
            target=Path(tmp)/'OriginOS';shutil.copytree(EXAMPLE/'OriginOS_PD2620',target)
            old_sf=(target/'system/system/bin/surfaceflinger').read_bytes()
            old_vendor=(target/'vendor/lib64/libsdmcore.so').read_bytes()
            session,r=patch(target,EXAMPLE/'OP13_ColorOS',log=lambda _:None)
            self.assertEqual(r['changed_partitions'],['system','vendor']);self.assertFalse(r['vendor_restoration'])
            self.assertEqual(len(r['cil']['chains']),3)
            after_sf=(target/'system/system/bin/surfaceflinger').read_bytes()
            self.assertNotEqual(old_sf,after_sf)
            vendor=(target/'vendor/lib64/libsdmcore.so').read_bytes()
            self.assertEqual(vendor.replace(b'/vendor/etc/cos_color//',b'/my_product/vendor/etc/'),old_vendor)
            sre=json_read((target/'system/system/etc/LcmConfig/LcmSreConfig.json').read_text())
            self.assertEqual(sre[0]['panel'][0]['hbmMap'],[3515,4094])
            self.assertIn('BEGIN MIO ORIGIN BRIGHTNESS',(target/'vendor/etc/selinux/vendor_sepolicy.cil').read_text())
            second,r2=patch(target,EXAMPLE/'OP13_ColorOS',log=lambda _:None)
            self.assertEqual((target/'system/system/bin/surfaceflinger').read_bytes(),after_sf)
            restore(second,lambda _:None);restore(session,lambda _:None)
            self.assertEqual((target/'system/system/bin/surfaceflinger').read_bytes(),old_sf)
            self.assertEqual((target/'vendor/lib64/libsdmcore.so').read_bytes(),old_vendor)
            self.assertFalse((target/RECEIPT).exists())

if __name__=='__main__':unittest.main(verbosity=2)
