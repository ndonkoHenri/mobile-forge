import unittest


class TestLxml(unittest.TestCase):
    def test_basic(self):
        """Loads the etree extension and parses a document through libxml2."""
        from lxml import etree

        parent = etree.fromstring(
            "<parent><child name='one'/><child name='two'/></parent>"
        )
        self.assertEqual("parent", parent.tag)
        self.assertEqual(2, len(parent))
        self.assertEqual("one", parent[0].get("name"))
        self.assertEqual("two", parent[1].get("name"))

    def test_objectify_shares_trees_with_etree(self):
        """Cross the etree/objectify boundary, which on iOS crosses two libxml2s.

        `flet-libxml2` is a static archive on iOS, so both extensions link their
        own copy: each *defines* `xmlFreeDoc` and `xmlDictCreate` and imports
        neither. Anything that allocates a node in one and touches it from the
        other therefore runs against two libxml2 instances with separate global
        state. Nothing else here exercises that — `test_basic` is etree alone.
        """
        from lxml import etree, objectify

        root = objectify.fromstring(
            "<readings><t>21.5</t><t>19.0</t><n>3</n></readings>"
        )
        # objectify's own node walking and type coercion.
        self.assertAlmostEqual(21.5, float(root.t[0]))
        self.assertEqual(3, int(root.n))

        # Allocated via objectify, serialised by etree, reparsed by etree.
        xml = etree.tostring(root)
        again = etree.fromstring(xml)
        self.assertEqual("readings", again.tag)
        self.assertEqual(3, len(again))

        # And the reverse direction: an etree tree handed to objectify.
        tree = etree.fromstring("<a><b>7</b></a>")
        objectify.deannotate(tree, cleanup_namespaces=True)
        self.assertEqual("7", tree.find("b").text)

    def test_parse_errors_raise_rather_than_escaping(self):
        """A malformed document must raise, from both extensions.

        lxml captures libxml2 diagnostics by installing a structured error
        handler. That handler is global to a libxml2 instance, so with one
        instance per extension it has to be installed in each — if objectify's
        copy has no handler, an error there has nothing to raise from and
        surfaces as text on stderr or as a wrong answer instead.
        """
        from lxml import etree, objectify

        with self.assertRaises(etree.XMLSyntaxError):
            etree.fromstring("<unclosed>")
        with self.assertRaises(etree.XMLSyntaxError):
            objectify.fromstring("<unclosed>")

    def test_xslt_transforms(self):
        """XSLT runs through libxslt, whose registries are global as well.

        libxslt keeps its extension-function and element registries in process
        globals, and `flet-libxslt` is static on iOS too — so this covers a
        second library with the same split, and the only path in the package
        that uses it.
        """
        from lxml import etree

        transform = etree.XSLT(
            etree.fromstring(
                """<xsl:stylesheet version="1.0"
                     xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
                     <xsl:template match="/"><out>
                       <xsl:value-of select="count(//item)"/>
                     </out></xsl:template>
                   </xsl:stylesheet>"""
            )
        )
        result = transform(etree.fromstring("<r><item/><item/><item/></r>"))
        self.assertEqual("3", str(result.getroot().text).strip())
