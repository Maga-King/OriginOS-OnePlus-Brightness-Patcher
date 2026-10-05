"""Offline narrowly-scoped patch regression tests; no phone writes."""
from pathlib import Path
import io, struct, unittest
from elftools.elf.elffile import ELFFile
from patch_cwb_buffer import patch

ROOT=Path(__file__).resolve().parent
class BufferPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=(ROOT/'origin_live_vendor_cwb.so').read_bytes()
        cls.patched,cls.report=patch(cls.original,1440,3168)

    def test_only_one_instruction_changed(self):
        original=ELFFile(io.BytesIO(self.original))
        patched=ELFFile(io.BytesIO(self.patched))
        a=original.get_section_by_name('.text')
        b=patched.get_section_by_name('.text')
        index=int(self.report['site'],16)-int(a['sh_addr'])
        self.assertEqual(a.data()[:index],b.data()[:index])
        self.assertEqual(a.data()[index+4:],b.data()[index+4:])
        self.assertEqual(len(self.original),len(self.patched))

    def test_literal_is_file_backed_without_load_relocation(self):
        address=int(self.report['literal'],16)
        original=ELFFile(io.BytesIO(self.original))
        patched=ELFFile(io.BytesIO(self.patched))
        loads=[s for s in patched.iter_segments() if s['p_type']=='PT_LOAD']
        holders=[s for s in loads if s['p_vaddr']<=address and address+8<=s['p_vaddr']+s['p_filesz']]
        self.assertEqual(len(holders),1)
        self.assertEqual(holders[0]['p_flags'],4)
        offset=holders[0]['p_offset']+address-holders[0]['p_vaddr']
        self.assertEqual(struct.unpack_from('<II',self.patched,offset),(1440,3168))
        for a,b in zip(original.iter_segments(),patched.iter_segments()):
            for key in ('p_type','p_flags','p_offset','p_vaddr','p_paddr','p_align'):
                self.assertEqual(a[key],b[key])

    def test_wrong_model_dimensions_rejected(self):
        with self.assertRaises(ValueError): patch(self.original,1264,2780)

    def test_occupied_gap_rejected(self):
        e=ELFFile(io.BytesIO(self.original))
        s=next(s for s in e.iter_segments() if s['p_type']=='PT_LOAD' and s['p_flags']==4)
        modified=bytearray(self.original)
        modified[s['p_offset']+s['p_filesz']]=1
        with self.assertRaisesRegex(ValueError,'zero gap'): patch(bytes(modified),1440,3168)

    def test_double_patch_rejected(self):
        with self.assertRaisesRegex(ValueError,'uniquely identified'): patch(self.patched,1440,3168)

    def test_repeatable(self):
        data,report=patch(self.original,1440,3168)
        self.assertEqual(data,self.patched)
        self.assertEqual(report,self.report)

if __name__=='__main__': unittest.main(verbosity=2)
